# Doublink Multilink System — Test Plan

| 文件資訊 | |
|----------|---|
| **文件名稱** | Doublink Multilink System Test Plan |
| **版本** | 1.0 |
| **日期** | 2026-04-17 |
| **適用系統** | Doublink ATSSS 5G+WiFi Multilink |
| **測試環境** | Tester: 192.168.105.210 |
| **撰寫者** | Network/5G Verification Team |

---

## 目錄

1. [測試範圍與目的](#1-測試範圍與目的)
2. [測試環境與架構](#2-測試環境與架構)
3. [測試分類概覽](#3-測試分類概覽)
4. [Group A — 模式切換測試（Mode Switching）](#4-group-a--模式切換測試)
5. [Group B — 網路劣化驗證（Degradation）](#5-group-b--網路劣化驗證)
6. [Group C — 黃金場景測試（Golden Scenarios）](#6-group-c--黃金場景測試)
7. [Group D — 連結權重與模式比較（Link Weight）](#7-group-d--連結權重與模式比較)
8. [Pass / Fail 判定標準](#8-pass--fail-判定標準)

---

## 1. 測試範圍與目的

本 Test Plan 涵蓋 Doublink ATSSS（Access Traffic Steering, Switching, Splitting）Multilink 系統的自動化驗證測試，共 **52 個測項**，分成 4 大功能群組。

**驗證重點：**
- ATSSS 三種模式（real_time / bonding / duplicate）的正確性與可切換性
- 在模擬 5G 與 WiFi 網路劣化條件下的資料平面行為
- 核心差異化功能：頻寬聚合、無感切換、丟包保護
- 系統在不同條件下能否維持最低可用吞吐量

---

## 2. 測試環境與架構

### 2.1 系統拓撲

```
                    Internet
                       │
        ┌──────────────┴──────────────┐
        │                             │
   wan_a_in                      wan_b_in
   [NetEmu]                      [NetEmu]
   lan_a_out                    lan_b_out
        │                             │
        └────────────┬────────────────┘
                     │
              Doublink Device
            (ATSSS Multilink)
                     │
              iperf3 Client
```

### 2.2 設備清單

| 設備 | IP / Port | 角色 |
|------|-----------|------|
| Doublink | 192.168.101.100:30008 | 受測裝置（DUT）— ATSSS 5G+WiFi 聚合 |
| NetEmu | 192.168.105.115:8080 | 網路仿真器（模擬 delay / loss / bandwidth） |
| iperf3 Server | 192.168.101.101:5201 | 流量量測端點 |
| Tester | 192.168.105.210 | 測試執行機（pytest + iperf3 client） |

### 2.3 NetEmu 介面對應

| 介面名稱 | 方向 | 對應路徑 |
|----------|------|---------|
| `wan_a_in` | LINE A 下行 | 5G Downlink |
| `lan_a_out` | LINE A 上行 | 5G Uplink |
| `wan_b_in` | LINE B 下行 | WiFi Downlink |
| `lan_b_out` | LINE B 上行 | WiFi Uplink |

### 2.4 ATSSS 模式定義

| 模式名稱 | 數值 | 行為描述 |
|----------|------|---------|
| `real_time` | 0 | 即時模式：根據即時條件選擇單一最佳路徑 |
| `bonding` | 3 | 聚合模式：分流封包至雙路徑，加總頻寬 |
| `duplicate` | 4 | 備援模式：同一封包同時送出至雙路徑，保護丟包 |

### 2.5 量測說明

> **tc htb 頻寬限制說明：** NetEmu 使用 Linux `tc htb` 進行限速，  
> 設定 60M kbit 的情況下，實際 TCP 吞吐量約 **25–30 Mbps**（約 50% overhead）。  
> 所有門檻值已依此特性校正。

---

## 3. 測試分類概覽

| Group | 分類 | 測項數 | 主要驗證功能 |
|-------|------|--------|------------|
| A | Mode Switching | 10 | 模式切換 API 正確性、切換過程中流量連續性 |
| B | Degradation | 22 | Profile 套用驗證、TCP/UDP 劣化量測、Steering、Recovery |
| C | Golden Scenarios | 6 | 核心功能：聚合、切換、丟包保護 |
| D | Link Weight | 9 | 各模式吞吐量比較、基準效能 |
| **合計** | | **52** | |

---

## 4. Group A — 模式切換測試

### 測試設定（共用）

| 項目 | 說明 |
|------|------|
| **執行檔** | `tests/test_mode_switching/test_mode_transitions.py` |
| **前置條件** | Doublink API 可達、iperf3 server 在線 |
| **量測工具** | iperf3 TCP（baseline: 5s，切換後: 10s） |
| **等待時間** | 模式切換後等待 15 秒穩定 |
| **恢復率計算** | `recovery_pct = after_switch_mbps / baseline_mbps × 100` |

---

#### A-01｜realtime_to_bonding_clean_tcp

| 欄位 | 內容 |
|------|------|
| **Test Item** | real_time → bonding 模式切換（clean 條件） |
| **Test Purpose** | 驗證從 real_time 切換至 bonding 模式後，流量能持續傳輸且吞吐量有效恢復 |
| **Test Setup** | 設定初始模式 real_time → 套用 clean_controlled（5G 60M/25ms/0.1%，WiFi 60M/10ms/0.1%）→ 量測 5s baseline → 執行模式切換 → 等待 15s → 量測 10s after_switch |
| **Test Condition** | Network: clean_controlled（雙線均有 60M kbit 限速）|
| **Expected Result** | 切換後吞吐量恢復率 ≥ **30%**，after_switch 吞吐量 > 0 Mbps |
| **實測參考值** | baseline ≈ 18.5 Mbps，after_switch ≈ 19.8 Mbps，recovery ≈ 107% |

---

#### A-02｜bonding_to_duplicate_symm_loss_http

| 欄位 | 內容 |
|------|------|
| **Test Item** | bonding → duplicate 模式切換（對稱輕度丟包條件） |
| **Test Purpose** | 驗證在 mild loss 環境下從聚合模式切換至備援模式，流量不中斷且切換後因 duplicate 保護，吞吐量明顯提升 |
| **Test Setup** | 設定初始模式 bonding → 套用 symmetric_mild_loss（雙線 50M/20ms/0.3%）→ 量測 baseline → 切換至 duplicate → 等待 15s → 量測 after_switch |
| **Test Condition** | Network: symmetric_mild_loss（雙線 50M kbit，20ms 延遲，0.3% 丟包）|
| **Expected Result** | 切換後恢復率 ≥ **50%**，成功率 ≥ 95%，after_switch > 0 Mbps |
| **實測參考值** | baseline ≈ 8.3 Mbps，after_switch ≈ 44.1 Mbps，recovery ≈ 531% |

---

#### A-03｜duplicate_to_realtime_symm_latency_tcp

| 欄位 | 內容 |
|------|------|
| **Test Item** | duplicate → real_time 模式切換（對稱高延遲條件） |
| **Test Purpose** | 驗證從高保護性備援模式退回即時模式後，流量仍可正常傳輸 |
| **Test Setup** | 設定初始模式 duplicate → 套用 symmetric_mild_latency（雙線 40M/60ms/8ms jitter）→ 量測 baseline → 切換至 real_time → 等待 15s → 量測 after_switch |
| **Test Condition** | Network: symmetric_mild_latency（雙線 40M kbit，60ms 延遲，8ms jitter）|
| **Expected Result** | 切換後恢復率 ≥ **50%**，after_switch > 0 Mbps |
| **實測參考值** | baseline ≈ 8.3 Mbps，after_switch ≈ 16.5 Mbps，recovery ≈ 199% |

---

#### A-04｜realtime_to_duplicate_congested_udp

| 欄位 | 內容 |
|------|------|
| **Test Item** | real_time → duplicate 模式切換（壅塞條件，UDP VoIP 流量） |
| **Test Purpose** | 驗證在嚴重壅塞環境下切換至 duplicate 模式能提升可靠性，模擬 VoIP 場景 |
| **Test Setup** | 設定初始模式 real_time → 套用 congested_recoverable（雙線 10M/80ms/1%）→ 量測 baseline → 切換至 duplicate → 等待 15s → 量測 after_switch |
| **Test Condition** | Network: congested_recoverable（雙線 10M kbit，80ms 延遲，1% 丟包）|
| **Expected Result** | 切換後恢復率 ≥ **40%**，成功率 ≥ 90%，after_switch > 0 Mbps |
| **實測參考值** | baseline ≈ 1.7 Mbps，after_switch ≈ 8.4 Mbps，recovery ≈ 490% |

---

#### A-05｜bonding_to_realtime_5g_intermittent_sip

| 欄位 | 內容 |
|------|------|
| **Test Item** | bonding → real_time 模式切換（5G 間歇抖動，SIP 流量） |
| **Test Purpose** | 驗證在 5G 間歇抖動場景下，從聚合模式切換至即時模式後系統仍可維持 SIP 通話品質 |
| **Test Setup** | 設定初始模式 bonding → 套用 5g_intermittent_visible（5G 每 15s 斷線 2s，WiFi 50M 正常）→ 量測 baseline → 切換至 real_time → 等待 15s → 量測 after_switch |
| **Test Condition** | Network: 5g_intermittent_visible（5G 50M + 週期斷線 2s/15s，WiFi 50M 正常）|
| **Expected Result** | 成功率 ≥ **85%**，after_switch > 0 Mbps |
| **實測參考值** | baseline ≈ 66 Mbps，after_switch ≈ 62 Mbps，recovery ≈ 94% |

---

#### A-06｜bonding_to_duplicate_5g_degraded_tcp

| 欄位 | 內容 |
|------|------|
| **Test Item** | bonding → duplicate 模式切換（5G 劣化，WiFi 正常） |
| **Test Purpose** | 驗證 5G 嚴重劣化時從聚合模式切換至備援模式，duplicate 能透過 WiFi 恢復較高吞吐量 |
| **Test Setup** | 設定初始模式 bonding → 套用 5g_degraded_moderate（5G 20M/60ms/1.5%，WiFi 40M/10ms/0.1%）→ 量測 baseline → 切換至 duplicate → 等待 15s → 量測 after_switch |
| **Test Condition** | Network: 5g_degraded_moderate（5G 劣化，WiFi 健康）|
| **Expected Result** | 切換後恢復率 ≥ **70%**，after_switch > 0 Mbps |
| **實測參考值** | baseline ≈ 1.0 Mbps，after_switch ≈ 18.9 Mbps，recovery ≈ 1853% |

---

#### A-07 / A-08 / A-09｜API 模式切換基本驗證

| 欄位 | 內容 |
|------|------|
| **Test Item** | bonding↔duplicate, duplicate↔real_time, real_time↔bonding API 切換 |
| **Test Purpose** | 驗證 Multilink API PUT mode 呼叫能正確完成，無 HTTP 錯誤 |
| **Test Setup** | 直接呼叫 `PUT /api/v1/agents/{agent_id}/mode` |
| **Test Condition** | 無網路劣化，無流量 |
| **Expected Result** | API 回傳 HTTP 200，`switched: true`，mode 數值對應正確 |
| **實測參考值** | 全部 PASS，回應時間 < 1s |

---

#### A-10｜負載中途切換模式

| 欄位 | 內容 |
|------|------|
| **Test Item** | iperf3 傳輸過程中執行模式切換（bonding → duplicate） |
| **Test Purpose** | 驗證 iperf3 session 在模式切換後不崩潰，能完整跑完並回傳有效吞吐量 |
| **Test Setup** | 設定 bonding 模式 → 啟動 15s iperf3（2 parallel）→ 第 5s 時切換至 duplicate → 等待 iperf3 完成 |
| **Test Condition** | 無 NetEmu 限速，進行中切換 |
| **Expected Result** | iperf3 完成（不因切換崩潰），吞吐量 > 0 Mbps |
| **實測參考值** | throughput ≈ 190.6 Mbps，duration ≈ 15.2s |

---

## 5. Group B — 網路劣化驗證

### 測試設定（共用）

| 項目 | 說明 |
|------|------|
| **執行檔** | `tests/test_degradation/test_throughput_degradation.py` |
| **前置條件** | NetEmu API 可達，Doublink API 可達 |
| **量測工具** | iperf3 TCP（10s，parallel=4）或 UDP（10s，bandwidth=10M） |

---

### B-01 ~ B-06｜Profile 套用驗證

#### B-01 ~ B-05｜ATSSS Profile 正確套用

| 欄位 | 內容 |
|------|------|
| **Test Item** | 驗證各 profile 在 NetEmu 上正確建立 4 條規則（A-DL, A-UL, B-DL, B-UL） |
| **Test Purpose** | 確保測試框架能透過 NetEmu API 正確套用雙線 profile，並驗證規則 status 為 active |
| **Test Setup** | 呼叫 `apply_network_condition(profile_id)` → 查詢 NetEmu `/api/rules/{id}` |
| **Test Condition** | 5 個 Profile：clean_controlled, symmetric_mild_loss, symmetric_mild_latency, 5g_degraded_moderate, wifi_degraded_moderate |
| **Expected Result** | 每個 profile 建立恰好 **4 條規則**，每條規則 status 為 `active` 或 `active_varied` |

---

#### B-06｜規則清除後恢復乾淨狀態

| 欄位 | 內容 |
|------|------|
| **Test Item** | 清除 NetEmu 規則後驗證 status 變為 cleared |
| **Test Purpose** | 確保測試結束後能正確還原網路狀態，不影響後續測項 |
| **Test Setup** | 套用 symmetric_mild_loss → 呼叫 `clear_rule(rule_id)` × 4 → 查詢各規則 |
| **Test Condition** | symmetric_mild_loss profile（4 條規則） |
| **Expected Result** | 每條規則 status 變為 `cleared` |

---

### B-07 ~ B-08｜動態變化 Profile 驗證

#### B-07｜WiFi 干擾動態變化

| 欄位 | 內容 |
|------|------|
| **Test Item** | wifi_interference_moderate profile 驗證 LINE B 規則具有 variation_enabled=true |
| **Test Purpose** | 確保動態變化功能（模擬 WiFi 干擾波動）有正確設定到 NetEmu 規則 |
| **Test Setup** | 套用 wifi_interference_moderate → 查詢 4 條規則的 variation_enabled 欄位 |
| **Test Condition** | wifi_interference_moderate：WiFi 35M/25ms/0.4% + variation（±15M, ±15ms, ±0.4%，每 3s 變化一次） |
| **Expected Result** | 至少 **2 條規則**（LINE B）有 `variation_enabled: true` |

---

#### B-08｜雙線動態變化

| 欄位 | 內容 |
|------|------|
| **Test Item** | both_varied_moderate profile 驗證 4 條規則均有 variation_enabled=true |
| **Test Purpose** | 確保 5G 與 WiFi 同時動態變化的場景能正確設定 |
| **Test Setup** | 套用 both_varied_moderate → 查詢 4 條規則 |
| **Test Condition** | both_varied_moderate：5G 40M+variation，WiFi 30M+variation，雙線同時波動 |
| **Expected Result** | **全部 4 條規則** `variation_enabled: true` |

---

### B-09 ~ B-10｜週期斷線 Schedule 驗證

| 欄位 | 內容 |
|------|------|
| **Test Item** | 5g_intermittent_visible / wifi_intermittent_visible 驗證斷線排程正確設定 |
| **Test Purpose** | 確認 NetEmu 的 disconnect_schedule 功能有正確套用到劣化線路，enabled=true |
| **Test Setup** | 套用對應 profile → 查詢 4 條規則的 disconnect_schedule 欄位 |
| **Test Condition** | 5g_intermittent_visible：5G 每 15s 斷線 2s × 10 次；wifi_intermittent_visible：WiFi 同規格 |
| **Expected Result** | 劣化線路的 **≥ 2 條規則** 有 `disconnect_schedule.enabled: true` |

---

### B-11｜TCP 基準量測

| 欄位 | 內容 |
|------|------|
| **Test Item** | 無 NetEmu 劣化條件下的 TCP 吞吐量基準 |
| **Test Purpose** | 建立 TCP 基準值，作為後續劣化測試的比較依據 |
| **Test Setup** | 不套用任何 profile → 執行 iperf3 TCP 10s，parallel=4 |
| **Test Condition** | 無 NetEmu 規則（clean 狀態） |
| **Expected Result** | TCP 吞吐量 > 0 Mbps（實測約 **130 Mbps**） |

---

### B-12 ~ B-17｜TCP 劣化條件量測

| Test ID | Test Item | Test Condition | Expected Result | 實測參考值 |
|---------|-----------|---------------|-----------------|-----------|
| **B-12** | TCP — symmetric_mild_loss | 雙線 50M / 20ms / **0.3% loss** | TCP ≥ **2.0 Mbps** | 35.9 Mbps |
| **B-13** | TCP — symmetric_mild_latency | 雙線 40M / **60ms** / 8ms jitter | TCP ≥ **1.0 Mbps** | 7.5 Mbps |
| **B-14** | TCP — congested_recoverable | 雙線 **10M / 80ms / 1% loss** | TCP ≥ **0.5 Mbps** | 6.0 Mbps |
| **B-15** | TCP — 5g_degraded_moderate | 5G **20M/60ms/1.5%**，WiFi 40M/10ms | TCP ≥ **1.0 Mbps** | 33.0 Mbps |
| **B-16** | TCP — wifi_degraded_moderate | WiFi **20M/40ms/1.5%**，5G 40M/20ms | TCP ≥ **1.0 Mbps** | 21.2 Mbps |
| **B-17** | TCP — asymmetric_mixed_moderate | 5G 40M/80ms/0.2%，WiFi **40M/20ms/1.5%** | TCP ≥ **1.0 Mbps** | 7.3 Mbps |

**共用測試設定：**

| 項目 | 說明 |
|------|------|
| **Test Setup** | 套用對應 profile（4 條 NetEmu 規則）→ 等待 5s 穩定 → 執行 iperf3 TCP 10s，parallel=4 |
| **Test Purpose** | 量測 ATSSS Multilink 在各種劣化條件下能維持的最低 TCP 吞吐量 |

---

### B-18｜UDP 基準量測

| 欄位 | 內容 |
|------|------|
| **Test Item** | 無 NetEmu 劣化條件下的 UDP 吞吐量基準 |
| **Test Purpose** | 建立 UDP 基準值，50M 送出速率下確認封包能正常通過 |
| **Test Setup** | 不套用任何 profile → 執行 iperf3 UDP 10s，bandwidth=50M |
| **Test Condition** | 無 NetEmu 規則（clean 狀態） |
| **Expected Result** | UDP 吞吐量 > 0 Mbps（實測約 50 Mbps）；loss_pct 為資訊性數據（duplicate 模式下 >100% 為正常） |

---

### B-19 ~ B-22｜UDP 劣化條件量測

| Test ID | Test Item | Test Condition | Expected Result |
|---------|-----------|---------------|-----------------|
| **B-19** | UDP — symmetric_mild_loss | 雙線 50M / 20ms / **0.3% loss** | UDP > 0 Mbps；loss ≤ **10%**（若 ≤100%） |
| **B-20** | UDP — symmetric_mild_latency | 雙線 40M / **60ms** / 8ms jitter | UDP > 0 Mbps；loss ≤ **60%**（若 ≤100%） |
| **B-21** | UDP — wifi_interference_moderate | WiFi 35M/25ms/0.4% + 動態變化 | UDP > 0 Mbps；loss ≤ **10%**（若 ≤100%） |
| **B-22** | UDP — asymmetric_mixed_moderate | 5G 40M/80ms，WiFi 40M/20ms/1.5% | UDP > 0 Mbps；loss ≤ **10%**（若 ≤100%） |

> **注意：** loss_pct > 100% 時，代表 ATSSS duplicate 模式送出重複封包，iperf3 計算失真，此情況僅驗證吞吐量 > 0，不驗證 loss。

---

### B-23 ~ B-26｜ATSSS 路由導向（Steering）驗證

**Test Purpose：** 當單一 link 劣化時，ATSSS 應自動將流量導向健康的 link，確保整體吞吐量不因單線故障而崩潰。

| Test ID | Test Item | Test Condition | Expected Result | 實測參考值 |
|---------|-----------|---------------|-----------------|-----------|
| **B-23** | Steering — 5G 劣化導向 WiFi | 5G 20M/60ms/1.5%，WiFi **40M/10ms** 健康 | TCP ≥ **1.0 Mbps** | 31.8 Mbps |
| **B-24** | Steering — WiFi 劣化導向 5G | WiFi 20M/40ms/1.5%，5G **40M/20ms** 健康 | TCP ≥ **1.0 Mbps** | 27.8 Mbps |
| **B-25** | Steering — 5G 高延遲導向 WiFi | 5G **50M/100ms**，WiFi **50M/10ms** 正常 | TCP ≥ **1.0 Mbps** | 36.2 Mbps |
| **B-26** | Steering — WiFi 高延遲導向 5G | WiFi **50M/100ms**，5G **50M/10ms** 正常 | TCP ≥ **1.0 Mbps** | 38.3 Mbps |

**Test Setup：** 套用對應 profile → 等待 5s → 執行 iperf3 TCP 10s，parallel=4

---

### B-27｜劣化後恢復驗證

| 欄位 | 內容 |
|------|------|
| **Test Item** | 壅塞條件解除後吞吐量恢復驗證 |
| **Test Purpose** | 驗證 NetEmu 規則清除後，ATSSS 能在 5 秒內恢復正常吞吐量，確認無殘留影響 |
| **Test Setup** | 套用 congested_recoverable（雙線 10M/80ms/1%）→ 量測 degraded 吞吐量（10s）→ 清除全部 4 條規則 → 等待 5s → 量測 recovered 吞吐量（10s） |
| **Test Condition** | congested_recoverable → 清除後無限速 |
| **Expected Result** | recovered > 0 Mbps；recovered / degraded ≥ **50%**（恢復不應比劣化中更差） |
| **實測參考值** | degraded ≈ 8.4 Mbps，recovered ≈ 109.7 Mbps，ratio ≈ 13× |

---

## 6. Group C — 黃金場景測試

### 測試設定（共用）

| 項目 | 說明 |
|------|------|
| **執行檔** | `tests/test_golden_scenarios/test_golden_scenarios.py` |
| **前置條件** | 所有元件正常、iperf3 server 在線 |
| **設計理念** | 直接驗證 Doublink 對外宣稱的核心差異化功能 |

---

#### C-01｜A1 — 均衡頻寬聚合

| 欄位 | 內容 |
|------|------|
| **Test Item** | 均衡 5G+WiFi bonding 聚合效能 |
| **Test Purpose** | 驗證 ATSSS bonding 模式能聚合雙路徑頻寬，在兩條線路等速時達到可量測的聚合效果 |
| **Test Setup** | 套用 golden_balanced_aggregation（5G 60M/25ms/0.1%，WiFi 60M/10ms/0.1%）→ 設定 bonding 模式 → 執行 iperf3 TCP 15s，parallel=4 |
| **Test Condition** | 5G：60M kbit / 25ms / 0.1% loss；WiFi：60M kbit / 10ms / 0.1% loss；模式：bonding |
| **Expected Result** | 吞吐量 ≥ **15 Mbps** |
| **實測參考值** | 23.3 Mbps（tc htb overhead 影響，實際可用頻寬約 25–30 Mbps/線） |

---

#### C-02｜A2 — 非均衡加權聚合（2:1 5G 偏重）

| 欄位 | 內容 |
|------|------|
| **Test Item** | 5G 80M + WiFi 40M，2:1 加權 bonding 聚合 |
| **Test Purpose** | 驗證 ATSSS bonding 在不對稱頻寬下（5G 容量較大）仍能有效聚合 |
| **Test Setup** | 套用 golden_weighted_aggregation（5G 80M/30ms/0.2%，WiFi 40M/10ms/0.2%）→ 設定 bonding 模式 → 執行 iperf3 TCP 15s，parallel=4 |
| **Test Condition** | 5G：80M kbit / 30ms / 0.2% loss；WiFi：40M kbit / 10ms / 0.2% loss；模式：bonding |
| **Expected Result** | 吞吐量 ≥ **10 Mbps** |
| **實測參考值** | 15.8 Mbps |

---

#### C-03｜B1 — 硬切換 Session 持續性

| 欄位 | 內容 |
|------|------|
| **Test Item** | 5G 週期斷線（每 20s 斷 3s），bonding 模式下 session 持續性 |
| **Test Purpose** | 驗證 ATSSS bonding 在 5G primary link 週期性完全斷線時，能透過 WiFi 維持 TCP session 不中斷 |
| **Test Setup** | 設定 bonding 模式 → 套用 golden_hard_failover（5G 50M/20ms + 每 20s 斷線 3s，WiFi 50M/10ms 正常）→ 執行 iperf3 TCP **30s**（覆蓋多次斷線週期） |
| **Test Condition** | 5G：50M kbit / 20ms，每 20s 斷線 3s × 5 次；WiFi：50M kbit / 10ms，持續正常；模式：bonding |
| **Expected Result** | iperf3 完整執行不崩潰，吞吐量 ≥ **5 Mbps** |
| **實測參考值** | 83.6 Mbps（WiFi 維持 session） |

---

#### C-04｜B2 — 間歇抖動長時間穩定性

| 欄位 | 內容 |
|------|------|
| **Test Item** | 5G 每 15s 抖動 2s（duplicate 模式下長達 60s） |
| **Test Purpose** | 驗證 ATSSS duplicate 模式在 5G 持續間歇抖動（每 15s 一次）時，透過 WiFi 冗餘路徑維持穩定吞吐量 |
| **Test Setup** | 設定 duplicate 模式 → 套用 golden_intermittent_flap（5G 50M + 每 15s 抖動 2s × 40 次，WiFi 50M 正常）→ 執行 iperf3 TCP **60s** |
| **Test Condition** | 5G：50M kbit，每 15s 斷線 2s；WiFi：50M kbit 持續正常；模式：duplicate |
| **Expected Result** | 60s 內維持吞吐量 ≥ **10 Mbps** |
| **實測參考值** | 45.3 Mbps |

---

#### C-05｜C1 — 丟包保護：duplicate vs bonding 比較

| 欄位 | 內容 |
|------|------|
| **Test Item** | 5G 2% 穩定丟包下，duplicate 模式 vs bonding 模式吞吐量比較 |
| **Test Purpose** | 驗證在高丟包環境下 duplicate 模式能提供更好的傳輸可靠性；同時確認兩種模式皆能維持基本連通 |
| **Test Setup** | 套用 golden_loss_protection（5G 40M/35ms/**2% loss**，WiFi 40M/12ms/0.2%）→ 切換 duplicate → 量測 15s → 切換 bonding → 量測 15s → 比較結果 |
| **Test Condition** | 5G：40M kbit / 35ms / **2% loss**；WiFi：40M kbit / 12ms / 0.2% loss |
| **Expected Result** | duplicate 模式吞吐量 > 0；bonding 模式吞吐量 > 0；duplicate 應明顯優於 bonding（因丟包保護） |
| **實測參考值** | duplicate ≈ 29.0 Mbps，bonding ≈ 1.8 Mbps（10× 差異） |

---

#### C-06｜C2 — 突發丟包韌性

| 欄位 | 內容 |
|------|------|
| **Test Item** | 5G 浮動丟包（0~10%）下 duplicate 模式韌性 |
| **Test Purpose** | 驗證 duplicate 模式在 5G 突發丟包（每 5 秒隨機 0~10%）時，透過 WiFi 冗餘確保整體吞吐量穩定 |
| **Test Setup** | 設定 duplicate 模式 → 套用 golden_burst_loss（5G 50M/10ms/5%±5% 變化，WiFi 50M 乾淨）→ 執行 iperf3 TCP **20s** |
| **Test Condition** | 5G：50M kbit / 10ms / 平均 5% loss，每 5s 隨機 0~10%；WiFi：50M kbit / 0ms / 0% loss；模式：duplicate |
| **Expected Result** | 吞吐量 ≥ **10 Mbps**（WiFi 路徑補償突發丟包） |
| **實測參考值** | 43.8 Mbps |

---

## 7. Group D — 連結權重與模式比較

### 測試設定（共用）

| 項目 | 說明 |
|------|------|
| **執行檔** | `tests/test_link_weight/test_weight_distribution.py` |
| **前置條件** | 所有元件正常 |
| **量測工具** | iperf3 TCP（10s, parallel=4）或 UDP（10s, 50M） |
| **設計理念** | 橫向比較三種模式在相同條件下的效能差異 |

---

### D-01 ~ D-07｜各模式條件效能量測

| Test ID | Test Item | 模式 | 網路條件 | Expected Result | 實測參考值 |
|---------|-----------|------|---------|-----------------|-----------|
| **D-01** | bonding — clean | bonding | clean_controlled（雙線 60M） | TCP ≥ **10 Mbps** | 21.1 Mbps |
| **D-02** | duplicate — clean | duplicate | clean_controlled（雙線 60M） | TCP ≥ **10 Mbps** | 49.3 Mbps |
| **D-03** | real_time — clean | real_time | clean_controlled（雙線 60M） | TCP ≥ **10 Mbps** | 27.1 Mbps |
| **D-04** | bonding — mild loss | bonding | symmetric_mild_loss（50M/0.3%） | HTTP success ≥ **90%** | 15.6 Mbps |
| **D-05** | duplicate — mild loss | duplicate | symmetric_mild_loss（50M/0.3%） | HTTP success ≥ **90%** | 39.3 Mbps |
| **D-06** | bonding — 5G degraded | bonding | 5g_degraded_moderate | TCP ≥ **1 Mbps** | 5.1 Mbps |
| **D-07** | bonding — WiFi degraded | bonding | wifi_degraded_moderate | TCP ≥ **1 Mbps** | 5.8 Mbps |

**Test Setup：** 設定對應模式 → 套用對應 profile（或不套用）→ 執行 iperf3

---

### D-08｜三模式 TCP 基準比較

| 欄位 | 內容 |
|------|------|
| **Test Item** | real_time / bonding / duplicate 三模式在無限速下的 TCP 基準比較 |
| **Test Purpose** | 建立各模式的最大效能基準，確認無任何 NetEmu 限速時三種模式均有效運作 |
| **Test Setup** | 不套用 NetEmu profile → 依序切換 real_time / bonding / duplicate → 各量測 iperf3 TCP 10s，parallel=4 |
| **Test Condition** | 無 NetEmu 限速（clean）|
| **Expected Result** | 三種模式吞吐量均 > 0 Mbps |
| **實測參考值** | real_time ≈ 349 Mbps，bonding ≈ 329 Mbps，duplicate ≈ 125 Mbps |

---

### D-09｜三模式 UDP 基準比較

| 欄位 | 內容 |
|------|------|
| **Test Item** | real_time / bonding / duplicate 三模式在無限速下的 UDP 基準比較 |
| **Test Purpose** | 驗證 UDP 封包在三種模式下均能有效傳輸；duplicate 模式的 loss_pct 異常為已知行為 |
| **Test Setup** | 不套用 NetEmu profile → 依序切換三模式 → 各量測 iperf3 UDP 10s，bandwidth=50M |
| **Test Condition** | 無 NetEmu 限速（clean）|
| **Expected Result** | 三種模式 UDP 吞吐量均 > 0 Mbps |
| **實測參考值** | real_time ≈ 50 Mbps / loss 0%；bonding ≈ 50 Mbps / loss 0%；duplicate ≈ 50 Mbps / loss ~350%（雙路送包） |

---

## 8. Pass / Fail 判定標準

### 8.1 通用判定原則

| 條件 | 判定 |
|------|------|
| `throughput_mbps > 0` 且符合門檻值 | **PASS** |
| `throughput_mbps == 0.0` 且 iperf3 有錯誤訊息 | 需看重試結果 |
| `throughput_mbps == 0.0` 經 3 次重試後仍 0 | **FAIL** |
| API 呼叫回傳非 200 / 拋出例外 | **FAIL** |

### 8.2 門檻值摘要

| 分類 | 指標 | 最低門檻 |
|------|------|---------|
| 模式切換恢復率 | recovery_pct | 30 ~ 70%（依測項） |
| TCP 劣化吞吐量 | throughput_mbps | 0.5 ~ 2.0 Mbps（依 profile） |
| ATSSS Steering | throughput_mbps | > 1.0 Mbps |
| 恢復後 vs 劣化中 | ratio | ≥ 0.50 |
| Golden A 聚合 | throughput_mbps | ≥ 10 ~ 15 Mbps |
| Golden B 切換持續 | throughput_mbps | ≥ 5 ~ 10 Mbps |
| Golden C 丟包保護 | throughput_mbps | > 0 Mbps（雙模式） |
| Link Weight 基準 | throughput_mbps | > 10 Mbps（有限速）|
| UDP 丟包率 | loss_pct | ≤ 10 ~ 60%（若 ≤ 100%；> 100% 為 duplicate 正常現象） |

### 8.3 已知特殊行為

| 現象 | 原因 | 處理方式 |
|------|------|---------|
| UDP loss_pct > 100% | duplicate 模式雙路送同一封包，iperf3 計算失真 | 僅驗證 throughput > 0，忽略 loss_pct |
| TCP 60M kbit cap 實際約 25–30 Mbps | tc htb overhead（約 50%） | 門檻值已校正 |
| iperf3 "server is busy" | 前一測試的 iperf3 session 未釋放 | 框架自動重試 3 次（間隔 5s）|
| iperf3 "Connection reset" | 模式切換短暫中斷 TCP 連線 | 框架自動重試 |

---

*文件路徑：`docs/TEST_PLAN.md` | Repo：`github.com/winson0728/doublink-tester` | 最後更新：2026-04-17*
