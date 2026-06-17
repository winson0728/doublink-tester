# 自動切換模組 — 算法說明

`src/doublink_tester/control/auto_mode_controller.py`

依 Doublinks `status2`/`links` API 提供的每路遙測（throughput、latency、loss、ATSSS weight），
自動在三種模式間切換：**Realtime / Bonding / Redundant(Duplicate)**。
所有閾值皆取自 74 測項每日回歸與黃金場景結果。

---

## 1. 整體架構 — 閉迴路

```
  ┌────────────────────────── 每 3 秒一輪 ──────────────────────────┐
  ▼                                                                  │
poll status2(/links)  →  特徵萃取 + 平滑  →  三模式評分  →  決策(防震盪)  →  set_mode()
  GET per-link            EWMA / window         [0,1] score        遲滯+確認+停留      PUT /mode
```

核心 `decide()` 是**純函式**（輸入特徵 → 輸出決策），可單獨測試、可解釋；
每次切換都附帶人類可讀的 `reason` 與三模式分數。

---

## 2. 三種模式與適用情境

| 模式 | API 值 | 何時選用 | 取自測試 |
|------|--------|---------|---------|
| **Realtime** | 0 | 鏈路**不對稱但穩定可逃避**：一條好、一條差（穩定丟包或高延遲）→ 導向較佳單路 | steering 測試（5g/wifi_degraded、*_high_latency） |
| **Bonding** | 3 | **雙路都真正健康**且容量相近 → 聚合衝吞吐 | 黃金 A1/A2 |
| **Redundant**(Duplicate) | 4 | **steering 逃不掉**：丟包波動、鏈路閃斷、嚴重穩定丟包(≥2%)、或雙路皆有損 | 黃金 C1/C2、B2 |

> 設計核心：**Redundant 只在「導向救不了」時才用**（它要耗雙倍頻寬）；
> 一條乾淨、一條穩定劣化時，用 Realtime 導向到乾淨路即可，較省。

---

## 3. 算法流程（逐步）

### Step 1 — 取樣
每 `poll_interval_s`（預設 **3 秒**，對齊鏈路取樣 cadence）呼叫一次 `fetch()` 取得 `list[LinkInfo]`。

### Step 2 — 特徵萃取與平滑（`_extract_features`）
每條鏈路（以 `socket_id` 為鍵）計算：

| 特徵 | 計算方式 | 用途 |
|------|---------|------|
| `loss_pct` | `max(loss_from, loss_to)` 的 **EWMA**(α=0.4) | 抗單點尖刺 |
| `loss_bursts` | window(10) 內 loss **向上跨越** 2% 線的次數 | 偵測「波動/突發」（非穩定死路） |
| `latency_ms` / `jitter_ms` | EWMA | 延遲品質 |
| `weight` | 最新 ATSSS 權重 | 演算法自身決策的回饋 |
| `capacity` | inbound + outbound throughput | 容量相近度 |
| `active` | `loss<80%` 且 `latency<2000ms` | **可達性**（不看 weight，避免把 standby 誤判為死） |
| `flapping` | window 內 active→inactive 轉換 ≥2 次 | 間歇斷線偵測 |

### Step 3 — 鏈路健康分數 `health ∈ [0,1]`
```
health = 0.6·loss_term + 0.3·lat_term + 0.1·jit_term
  loss_term = clamp(1 − loss/2.0)        # 0% →1，2% →0
  lat_term  = clamp(1 − (lat−60)/40)     # ≤60ms →1，≥100ms →0
  jit_term  = clamp(1 − (jit−30)/60)     # ≤30ms →1，≥90ms →0
若 flapping 或 not active → health ×= 0.3
```

### Step 4 — 三模式評分（`_score_modes`）
**(a) 可靠度風險 `risk`（驅動 REDUNDANT）** = 下列取最大值：

| 風險來源 | 公式 | 對應場景 |
|---------|------|---------|
| 穩定重損 `steady_severe` | `smoothstep(loss, 1.5, 2.5)`（**僅 active 鏈路**） | C1（2%） |
| 波動 `volatile` | `smoothstep(loss_bursts, 1, 3)`（所有鏈路） | C2 突發 |
| 閃斷 `flap` | 任一 flapping → 1 | B2 間歇斷線 |
| 雙路皆損 `both_lossy` | `smoothstep(min_active_loss, 0.5, 2.0)`（≥2 active 時） | congested |

**(b) 三模式分數：**
```
score_redundant = risk
score_bonding   = smoothstep(min_health, 0.6, 0.9) · comparability · (1−risk)
                  若 active 鏈路 < 2 → ×0.2（單路無法聚合）
score_realtime  = asymmetry · max_health · (1−risk)
                  若 active 鏈路 < 2 → max(上式, 0.7·max_health)（單路 failover）
```
其中
- `asymmetry = max_health − min_health`（一條明顯較好 → 偏 Realtime）
- `comparability = clamp(min_cap / max_cap / 0.5)`（容量相近 → Bonding 聚合有效；A2 的 2:1 仍可聚合）

### Step 5 — 決策與防震盪（`decide`）
這是把「測試教訓：Weight 在兩線路間震盪 = 不穩定」落實的關鍵：

```
candidate = argmax(score_realtime, score_bonding, score_redundant)

① 遲滯邊界 (hysteresis margin)
   若 candidate ≠ 現任 且 score[candidate] − score[現任] < 0.15 → 維持現任

② 確認窗 (confirmation window)
   挑戰者需連續 confirm_samples(3) 次勝出，才允許切換（3×3s = 9s）

③ 最短停留 (min dwell)
   距上次切換 < min_dwell_s(20s) → 即使決策改變也不致動
   （對齊隧道重建/模式 settle 時間）

④ 無遙測 → 維持現任（API 異常不亂切）
```

---

## 4. 閾值來源 — 直接對應測試結果

| 參數 | 預設 | 依據 |
|------|------|------|
| `loss_redundant_pct` | **2.0%** | 黃金 C1 邊界（duplicate 成功率 0.98 > bonding 0.90） |
| 穩定重損 ramp | 1.5%–2.5% | 1.5% 穩定 → Realtime 導向；2.0% → Redundant |
| `latency_high_ms` | **100ms** | `5g_high_latency_moderate` profile |
| `latency_healthy_ms` | 60ms | clean profiles 落在 10–25ms |
| `bonding_capacity_ratio` | **0.5** | 黃金 A2 以 2:1（80M/40M）成功聚合 |
| `poll_interval_s` | 3s | 與鏈路取樣 cadence 一致 |
| `min_dwell_s` | 20s | 模式切換 settle 時間（`mode_switch_s`） |
| `confirm_samples` | 3 | 3×3s=9s < 10s「健康反應」目標 |

---

## 5. 場景驗證（12 個回歸測試，`tests/test_control/`）

| 網路狀況 | 選擇 | 理由 |
|---------|------|------|
| clean_controlled（雙路健康） | **Bonding** | 雙健康相近 → 聚合 |
| symmetric_mild_loss 0.3% | **Bonding** | 輕微對稱損,仍可聚合 |
| 5g_degraded 1.5%（穩定） | **Realtime** | 一健康一穩定劣化 → 導向 |
| 5g_high_latency 100ms | **Realtime** | 延遲驅動導向 |
| C1 loss 2.0% | **Redundant** | 達 C1 邊界 → 複製保護 |
| congested 1% 雙路 | **Redundant** | 無乾淨路可導 |
| C2 burst 0–10% | **Redundant** | 波動 → 複製 |
| B2 間歇閃斷 | **Redundant** | 閃斷 → 複製 |
| hard_failover（5G 全斷） | **Realtime** | 死路無法複製 → 單路存活 |
| 單一瞬間尖刺(8%) | **不切換** | 遲滯+確認窗擋下 |

---

## 6. 參數調校（`ControllerConfig`）

所有閾值集中於 `ControllerConfig` dataclass,可不改邏輯直接覆寫。上線後建議：

- 以真實 5G/Wi-Fi 遙測重新校準 `loss_*` / `latency_*`（實驗室是 NetEmu tc 塑形,與實場有差）。
- 切換太頻繁 → 調大 `switch_margin`、`confirm_samples`、`min_dwell_s`。
- 反應太慢 → 調小 `poll_interval_s`、`confirm_samples`。

### 後續：從回歸資料學習
74 測項每日回歸 + 每秒鏈路取樣 = 一份**已標註訓練資料**（特徵 → 最佳模式）。
v2 可訓練分類器（如 gradient-boosted tree）持續微調閾值,並把規則式策略當「安全護欄」。

---

## 7. 多用戶擴展（server 端集中式）

`decide()` 無狀態、每 CPE 獨立 → 可水平分片。
若 `status2` 為批次 API（一次回多 CPE）,則查詢次數為**常數**（每 3 秒 1 次,與用戶數無關）;
瓶頸只剩線性的本地 CPU/記憶體（萬級 CPE 仍單核個位數百分比）。
詳見「批次讀 → 扇出 → 批次寫」架構。
