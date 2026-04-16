# Doublink 自動化測試使用手冊

> 版本：1.0 | 適用對象：網路/5G 工程師 | 環境：ATSSS 5G+WiFi Multilink

---

## 目錄

1. [系統架構概覽](#1-系統架構概覽)
2. [測試環境說明](#2-測試環境說明)
3. [快速開始](#3-快速開始)
4. [測試分類與說明](#4-測試分類與說明)
5. [執行測試](#5-執行測試)
6. [分析測試結果](#6-分析測試結果)
7. [自訂測試參數](#7-自訂測試參數)
8. [常見問題排除](#8-常見問題排除)
9. [附錄：流量數據參考值](#9-附錄流量數據參考值)

---

## 1. 系統架構概覽

```
┌─────────────────────────────────────────────────────────────────┐
│                         測試拓撲                                 │
│                                                                  │
│  Internet                                                        │
│     │                                                            │
│     ├─ wan_a_in ──[NetEmu Bridge]── lan_a_out ─→ LINE A (5G)    │
│     └─ wan_b_in ──[NetEmu Bridge]── lan_b_out ─→ LINE B (WiFi)  │
│                                                                  │
│  LINE A/B 匯聚到 Multilink (ATSSS) 裝置                          │
└─────────────────────────────────────────────────────────────────┘
```

### 主要元件

| 元件 | IP / 說明 |
|------|-----------|
| **Multilink** | `192.168.101.100:30008` — ATSSS 5G+WiFi 聚合裝置 |
| **NetEmu** | `192.168.105.115:8080` — 網路仿真器（模擬 delay/loss/bandwidth） |
| **iperf3 Server** | `192.168.101.101:5201` — 流量量測伺服器 |
| **Tester (執行機)** | `192.168.105.210` — 跑 pytest 的主機（user: ataya） |

### ATSSS 模式

| 模式名稱 | 數值 | 說明 |
|----------|------|------|
| `real_time` | 0 | 即時模式，單路徑優先 |
| `bonding` | 3 | 聚合模式，雙路徑加總頻寬 |
| `duplicate` | 4 | 備援模式，雙路同時傳送，保護丟包 |

---

## 2. 測試環境說明

### 2.1 網路 Profile 架構

每個 profile 定義 **LINE A（5G）** 與 **LINE B（WiFi）** 各自的網路條件：

```yaml
# config/profiles/network_conditions.yaml 範例
- id: 5g_degraded_moderate
  line_a:           # 5G
    bandwidth_kbit: 20000    # 20 Mbps
    delay_ms: 60             # 60ms 延遲
    loss_pct: 1.5            # 1.5% 丟包
  line_b:           # WiFi
    bandwidth_kbit: 40000    # 40 Mbps
    delay_ms: 10             # 10ms 延遲
    loss_pct: 0.1            # 0.1% 丟包
```

套用一個 profile 會在 NetEmu 的 4 個 interface 上各建立一條 tc 規則：
- `wan_a_in`（5G 下行）、`lan_a_out`（5G 上行）
- `wan_b_in`（WiFi 下行）、`lan_b_out`（WiFi 上行）

> **⚠️ 重要注意事項（tc htb 頻寬限制）**  
> NetEmu 用 `tc htb` 限速。例如設定 60M kbit，實際 TCP 吞吐量約為 25–30 Mbps（因 htb overhead）。  
> 測試門檻值皆已依此校正。

### 2.2 測試矩陣（Test Matrix）

測試案例從 `config/test_matrices/` YAML 讀取，無需修改 Python 程式碼即可調整測項。

---

## 3. 快速開始

### 3.1 登入執行機

```bash
ssh ataya@192.168.105.210
# 密碼：ataya
```

### 3.2 進入專案目錄

```bash
cd ~/doublink-tester
export PATH=$HOME/.local/bin:$PATH
```

### 3.3 執行全套測試（52 個測項）

```bash
# 方式一：使用 run_tests.sh（建議）
./scripts/run_tests.sh --all

# 方式二：直接用 pytest
PYTHONPATH=src:$PYTHONPATH pytest \
  tests/test_mode_switching/ \
  tests/test_degradation/test_throughput_degradation.py \
  tests/test_golden_scenarios/ \
  tests/test_link_weight/ \
  -v --timeout=600 --alluredir=allure-results
```

預期執行時間：**約 16 分鐘**

### 3.4 查看快速結果摘要

```bash
# 從 allure-results 提取流量數據
python3 scripts/extract_allure_data.py allure-results
```

---

## 4. 測試分類與說明

### 4.1 模式切換測試 `test_mode_switching/`

**驗證目的**：在流量傳輸中切換 ATSSS 模式，確認吞吐量不中斷。

| 測項 ID | 切換 | 網路條件 | 流量類型 | 通過門檻 |
|---------|------|----------|----------|---------|
| `realtime_to_bonding_clean_tcp` | real_time → bonding | clean_controlled | TCP | 恢復率 ≥ 30% |
| `bonding_to_duplicate_symm_loss_http` | bonding → duplicate | symmetric_mild_loss | HTTP | 恢復率 ≥ 50% |
| `duplicate_to_realtime_symm_latency_tcp` | duplicate → real_time | symmetric_mild_latency | TCP | 恢復率 ≥ 50% |
| `realtime_to_duplicate_congested_udp` | real_time → duplicate | congested_recoverable | UDP VoIP | 恢復率 ≥ 40% |
| `bonding_to_realtime_5g_intermittent_sip` | bonding → real_time | 5g_intermittent | SIP | 成功率 ≥ 85% |
| `bonding_to_duplicate_5g_degraded_tcp` | bonding → duplicate | 5g_degraded | TCP | 恢復率 ≥ 70% |

**恢復率計算公式**：
```
recovery_pct = (after_switch_mbps / baseline_mbps) × 100
```

---

### 4.2 網路劣化測試 `test_degradation/test_throughput_degradation.py`

**驗證目的**：在各種網路劣化條件下量測實際吞吐量。

**包含子類別：**

| 子類別 | 說明 |
|--------|------|
| `TestNetworkConditionApplied` | 驗證 profile 有正確套用到 NetEmu（4 條規則） |
| `TestDegradationWithVariation` | 驗證動態變化 profile（variation_enabled） |
| `TestDisconnectSchedule` | 驗證週期斷線 schedule 已設定 |
| `TestTcpThroughputDegradation` | 在各 profile 下量測 TCP 吞吐量 |
| `TestUdpDegradation` | 在各 profile 下量測 UDP 吞吐量與 Jitter |
| `TestSteeringBehaviour` | 驗證 ATSSS 能自動導向較佳路徑 |
| `TestRecoveryAfterDegradation` | 移除劣化後流量能否快速恢復 |

---

### 4.3 黃金場景測試 `test_golden_scenarios/`

**驗證目的**：6 個核心使用情境，直接測試 Doublink 的差異化功能。

| 場景 | 描述 | 預期結果 |
|------|------|---------|
| **A1** 均衡聚合 | 5G+WiFi 各 60M，bonding 模式 | 吞吐量 ≥ 15 Mbps |
| **A2** 加權聚合 | 5G 80M + WiFi 40M，2:1 偏重 | 吞吐量 ≥ 10 Mbps |
| **B1** 硬切換 | 5G 每 20s 斷線 3s，bonding 保持 session | 吞吐量 ≥ 5 Mbps |
| **B2** 間歇抖動 | 5G 每 15s 抖動 2s（持續 10 分鐘） | 吞吐量 ≥ 10 Mbps |
| **C1** 丟包保護 | 5G 2% loss，duplicate vs bonding 比較 | duplicate 明顯優於 bonding |
| **C2** 突發丟包 | 5G 0~10% 浮動丟包，duplicate 恢復 | 吞吐量 ≥ 10 Mbps |

---

### 4.4 連結權重測試 `test_link_weight/`

**驗證目的**：比較三種模式在相同條件下的實際吞吐量差異。

| 測項 | 模式 | 條件 |
|------|------|------|
| `bonding_clean_tcp` | bonding | clean_controlled |
| `duplicate_clean_tcp` | duplicate | clean_controlled |
| `realtime_clean_tcp` | real_time | clean_controlled |
| `test_all_modes_baseline_tcp` | 三種模式 | 無 NetEmu 限速 |
| `test_all_modes_baseline_udp` | 三種模式 | 無 NetEmu 限速 |

---

## 5. 執行測試

### 5.1 執行單一分類

```bash
cd ~/doublink-tester
export PATH=$HOME/.local/bin:$PATH

# 只跑模式切換
./scripts/run_tests.sh mode_switching

# 只跑黃金場景
PYTHONPATH=src:$PYTHONPATH pytest tests/test_golden_scenarios/ -v --timeout=600 --alluredir=allure-results

# 只跑劣化測試
PYTHONPATH=src:$PYTHONPATH pytest tests/test_degradation/test_throughput_degradation.py -v

# 只跑連結權重
./scripts/run_tests.sh link_weight
```

### 5.2 執行特定單一測項

```bash
# 執行單個 test function
PYTHONPATH=src:$PYTHONPATH pytest \
  "tests/test_golden_scenarios/test_golden_scenarios.py::TestBondingAggregation::test_balanced_aggregation" \
  -v --timeout=120

# 執行特定 parametrize ID
PYTHONPATH=src:$PYTHONPATH pytest \
  "tests/test_mode_switching/test_mode_transitions.py::TestModeTransitions::test_mode_switch_continuity[realtime_to_bonding_clean_tcp]" \
  -v
```

### 5.3 用 Marker 過濾

```bash
# 跳過慢速測試（標記為 @pytest.mark.slow）
PYTHONPATH=src:$PYTHONPATH pytest tests/ -v -m "not slow"

# 只跑特定分類
PYTHONPATH=src:$PYTHONPATH pytest tests/ -v -m "mode_switching"
PYTHONPATH=src:$PYTHONPATH pytest tests/ -v -m "degradation"
```

### 5.4 在背景執行（適合長時間測試）

```bash
# 執行並將輸出存檔
nohup bash -c 'cd ~/doublink-tester && export PATH=$HOME/.local/bin:$PATH && PYTHONPATH=src:$PYTHONPATH pytest tests/ -v --timeout=600 --alluredir=allure-results 2>&1' > ~/test_run.log &

# 追蹤進度
tail -f ~/test_run.log
```

### 5.5 清除舊的 allure 結果

```bash
echo ataya | sudo -S rm -rf ~/doublink-tester/allure-results
# 或
rm -rf ~/doublink-tester/allure-results/*
```

---

## 6. 分析測試結果

### 6.1 即時查看流量數據

```bash
cd ~/doublink-tester
python3 scripts/extract_allure_data.py allure-results
```

**輸出範例：**
```
✅ A1: Balanced 5G+WiFi aggregation
    scenario: A1
    profile: golden_balanced_aggregation
    mode: bonding
    throughput_mbps: 23.33

✅ Switch bonding -> duplicate | symmetric_mild_loss | http_load
    from_mode: bonding
    to_mode: duplicate
    baseline_mbps: 8.30
    after_switch_mbps: 44.07

❌ TCP throughput — 5g_degraded_moderate
    throughput_mbps: 0.00
    ⚠ AssertionError: TCP throughput 0.00 Mbps below minimum 1.0 Mbps
```

### 6.2 pytest 原始輸出解讀

```
PASSED [  7%]  → 測項通過，後方百分比為完成進度
FAILED [ 42%]  → 測項失敗，查看 FAILURES 區塊取得詳情
```

**失敗訊息範例與解讀：**

| 訊息 | 原因 | 處理方式 |
|------|------|---------|
| `Post-switch recovery 38% below minimum 40%` | 切換後吞吐量恢復不足 | 檢查 Multilink 模式切換 API 是否正常 |
| `TCP throughput 0.00 Mbps below minimum` | iperf3 無法連線伺服器 | 檢查 iperf3 server 是否在線，或等重試（自動重試 3 次） |
| `server is busy running a test` | iperf3 server 被前一個測試佔用 | 測試框架會自動重試 5 秒後再試 |
| `No throughput after mode switch` | 模式切換時 TCP 連線被中斷 | 屬於正常現象，重試後應恢復 |
| `UDP loss 1563% exceeds maximum` | ATSSS duplicate 模式雙路送包，iperf3 誤算丟包率 | 正常，>100% 的 UDP loss 在 duplicate 模式下為已知行為 |

### 6.3 產生 Allure HTML 報表

```bash
cd ~/doublink-tester

# 安裝 allure（僅需一次）
# 方式一：npm（推薦）
npm install -g allure-commandline

# 方式二：下載 binary
wget https://github.com/allure-framework/allure2/releases/download/2.29.0/allure-2.29.0.tgz
tar xzf allure-2.29.0.tgz
sudo ln -s $(pwd)/allure-2.29.0/bin/allure /usr/local/bin/allure

# 產生靜態報表
allure generate allure-results -o allure-report --clean

# 用 HTTP server 查看（在執行機上）
cd allure-report && python3 -m http.server 8888

# 在本機瀏覽器開啟（需要 SSH port forward）
# 在本機執行：
ssh -L 8888:localhost:8888 ataya@192.168.105.210
# 然後瀏覽器開啟 http://localhost:8888
```

### 6.4 測試結果資料夾結構

```
allure-results/
├── xxxxxxxx-result.json    ← 每個測項的結果（含附加的 JSON 數據）
├── xxxxxxxx-attachment.json ← 流量量測數據（throughput_mbps, loss_pct 等）
└── ...（共 ~52 個測項）
```

每個 `*-result.json` 包含：
- `name`：測項名稱
- `status`：`passed` / `failed` / `broken`
- `attachments`：含有流量數據的 JSON 附件

---

## 7. 自訂測試參數

### 7.1 修改網路 Profile

編輯 `config/profiles/network_conditions.yaml`：

```yaml
- id: my_custom_profile
  name: "自訂測試情境"
  line_a:                      # 5G
    bandwidth_kbit: 30000      # 30 Mbps 限速
    delay_ms: 50               # 50ms 延遲
    loss_pct: 2.0              # 2% 丟包
  line_b:                      # WiFi
    bandwidth_kbit: 50000      # 50 Mbps
    delay_ms: 15
    loss_pct: 0.2
```

**可用欄位：**

| 欄位 | 單位 | 說明 |
|------|------|------|
| `bandwidth_kbit` | kbit/s | 頻寬上限（0 = 不限） |
| `delay_ms` | ms | 固定延遲 |
| `jitter_ms` | ms | 抖動（隨機延遲變化） |
| `loss_pct` | % | 丟包率（0.0 ~ 100.0） |
| `corrupt_pct` | % | 封包損毀率 |
| `duplicate_pct` | % | 封包複製率 |

**週期斷線設定：**
```yaml
disconnect_schedule:
  enabled: true
  disconnect_s: 5      # 每次斷線秒數
  interval_s: 30       # 斷線間隔（週期）
  repeat: 5            # 重複次數
```

**動態變化設定：**
```yaml
variation:
  bw_range_kbit: 10000    # 頻寬每次隨機變化範圍
  delay_range_ms: 20      # 延遲每次隨機變化範圍
  loss_range_pct: 0.5     # 丟包率每次隨機變化範圍
  interval_s: 5           # 每幾秒更新一次
```

### 7.2 修改模式切換測試矩陣

編輯 `config/test_matrices/mode_switching.yaml`：

```yaml
matrix:
  - id: "my_test_case"
    from_mode: real_time       # 起始模式
    to_mode: bonding           # 切換目標模式
    network_condition: 5g_degraded_moderate  # 使用哪個 profile
    traffic: tcp_throughput    # 流量類型
    assertions:
      max_traffic_interruption_s: 3.0    # 允許最長中斷秒數
      min_throughput_recovery_pct: 50    # 切換後吞吐量恢復率
```

**模式名稱：** `real_time` / `bonding` / `duplicate`

**流量類型：** `tcp_throughput` / `http_load` / `udp_voip` / `sip_calls`

### 7.3 修改劣化測試門檻

編輯 `config/test_matrices/degradation.yaml`：

```yaml
matrix:
  - id: "tcp_symmetric_mild_loss"
    profile: symmetric_mild_loss
    traffic: tcp_throughput
    assertions:
      min_throughput_mbps: 2.0    # 最低要求吞吐量（Mbps）
      max_loss_pct: 10.0          # 最大允許丟包率（%）
```

### 7.4 修改全域設定

編輯 `config/settings.yaml`：

```yaml
doublink:
  netemu_url: "http://192.168.105.115:8080"    # NetEmu 位址
  multilink_url: "http://192.168.101.100:30008" # Multilink API 位址
  multilink_agent_id: "100000018"               # Agent ID
  iperf3_server: "192.168.101.101"              # iperf3 server

  timeouts:
    mode_switch_s: 15       # 切換後等待穩定的秒數
    network_settle_s: 5     # 套用 profile 後等待秒數
    traffic_start_s: 10     # 流量啟動等待秒數
```

---

## 8. 常見問題排除

### Q1：iperf3 連線失敗（0 Mbps）

**症狀：** `TCP throughput 0.00 Mbps below minimum`

**原因與排查：**
```bash
# 1. 確認 iperf3 server 是否在線
ping 192.168.101.101

# 2. 確認 iperf3 server 程序是否執行中
ssh ataya@192.168.101.101 "pgrep -a iperf3"

# 3. 手動測試連線
iperf3 -c 192.168.101.101 -p 5201 -t 5
```

**解決方法：**
- 若 server 沒在跑：`ssh ataya@192.168.101.101 "iperf3 -s -D"`
- 框架會自動重試 3 次（間隔 5 秒），稍等即可

### Q2：NetEmu 規則未正確套用

**症狀：** `test_network_condition_applied` 失敗，規則數量不符

```bash
# 查看目前所有 NetEmu 規則
curl -s http://192.168.105.115:8080/api/rules/ | python3 -m json.tool

# 清除所有規則
curl -s http://192.168.105.115:8080/api/rules/ | python3 -c "
import sys,json
rules = json.load(sys.stdin)
import subprocess
for r in rules:
    subprocess.run(['curl','-s','-X','POST',f'http://192.168.105.115:8080/api/rules/{r[\"id\"]}/clear'])
print(f'Cleared {len(rules)} rules')
"
```

### Q3：Multilink API 無回應

**症狀：** `set_multilink_mode` 失敗

```bash
# 確認 Multilink API 是否正常
curl -s http://192.168.101.100:30008/api/v1/agents/100000018/mode

# 預期回應：{"mode": 3, "mode_name": "bonding", ...}
```

### Q4：測試跑到一半中斷（timeout）

**症狀：** `Timeout` 或連線掉了

```bash
# 增加 timeout 上限（預設 600s）
PYTHONPATH=src:$PYTHONPATH pytest tests/ --timeout=1200 -v

# 或針對特定慢速測試
PYTHONPATH=src:$PYTHONPATH pytest tests/ -m "not slow" --timeout=300
```

### Q5：UDP 顯示極高丟包率（>100%）

**這是正常現象，不是錯誤。**

在 ATSSS `duplicate` 模式下，兩條路徑都會傳送同一個封包，iperf3 server 端收到重複封包，導致丟包率計算超過 100%。框架已針對此情況跳過 loss 斷言，只確認有流量即可。

### Q6：`allure-results` 被前一次測試佔用

```bash
# 用 sudo 強制刪除（舊結果可能由不同 user 建立）
echo ataya | sudo -S rm -rf ~/doublink-tester/allure-results
mkdir -p ~/doublink-tester/allure-results
```

---

## 9. 附錄：流量數據參考值

以下為標準測試環境的**正常預期值**（供結果比較用）：

### TCP Baseline（無 NetEmu 限速）

| 模式 | 吞吐量 Mbps |
|------|------------|
| real_time | ~340–350 |
| bonding | ~320–350 |
| duplicate | ~120–130 |

> duplicate 模式吞吐量較低是正常的，因為它在兩條路徑傳送相同資料，並非聚合。

### 有 NetEmu 限速的 TCP（60M kbit cap）

| 模式 | 條件 | 實際吞吐量 Mbps |
|------|------|----------------|
| real_time | clean_controlled (60M+60M) | ~25–30 |
| bonding | clean_controlled (60M+60M) | ~20–28 |
| duplicate | clean_controlled (60M+60M) | ~45–50 |

> ⚠️ 60M kbit cap 在 tc htb 下實際吞吐量約 25–30 Mbps（約 50% overhead）

### 黃金場景參考值

| 場景 | 典型吞吐量 Mbps |
|------|----------------|
| A1 均衡聚合 (bonding) | 23–30 |
| A2 加權聚合 (bonding) | 15–20 |
| B1 硬切換 (bonding) | 80–100 |
| B2 間歇抖動 (duplicate) | 40–50 |
| C1 丟包保護 duplicate | 25–40 |
| C1 丟包保護 bonding | 1–5（劣化嚴重） |
| C2 突發丟包 (duplicate) | 40–50 |

### ATSSS Steering 參考值

| Profile | 典型吞吐量 Mbps | 備註 |
|---------|----------------|------|
| 5g_degraded_moderate | 25–35 | 導向 WiFi |
| wifi_degraded_moderate | 25–30 | 導向 5G |
| 5g_high_latency_moderate | 30–40 | 導向 WiFi |
| wifi_high_latency_moderate | 35–40 | 導向 5G |

---

## 快速參考卡

```bash
# === 登入 ===
ssh ataya@192.168.105.210

# === 進入目錄 ===
cd ~/doublink-tester && export PATH=$HOME/.local/bin:$PATH

# === 執行全套 ===
PYTHONPATH=src:$PYTHONPATH pytest tests/test_mode_switching/ \
  tests/test_degradation/test_throughput_degradation.py \
  tests/test_golden_scenarios/ tests/test_link_weight/ \
  -v --timeout=600 --alluredir=allure-results

# === 查看結果 ===
python3 scripts/extract_allure_data.py allure-results | less

# === 只看 PASS/FAIL ===
python3 scripts/extract_allure_data.py allure-results | grep -E "(✅|❌)"

# === 清除舊結果 ===
echo ataya | sudo -S rm -rf ~/doublink-tester/allure-results

# === 只跑黃金場景 ===
PYTHONPATH=src:$PYTHONPATH pytest tests/test_golden_scenarios/ -v

# === 只跑特定 profile ===
PYTHONPATH=src:$PYTHONPATH pytest tests/ -k "5g_degraded" -v
```

---

*文件維護：`docs/TEST_MANUAL.md` | Repo：`github.com/winson0728/doublink-tester`*
