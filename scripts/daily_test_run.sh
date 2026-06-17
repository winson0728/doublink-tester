#!/usr/bin/env bash
# =============================================================================
# daily_test_run.sh — 每日自動測試 + 報告生成
#
# 排程：每日 02:00 由 cron 執行（測試時長延長至 ~3h 50min 後，提前開始以避開
#       工作時段；預計 02:00 → 約 05:50 完成）
# 輸出：
#   ~/doublink-tester/allure-results/   → allure JSON 原始結果
#   ~/doublink-tester/allure-report/    → allure HTML 報告
#   ~/doublink-tester/reports/          → Word 報告 + 測試日誌
#   http://192.168.105.210:8888/        → HTML 報告 Web 存取
# =============================================================================

set -eo pipefail
# 注意：不用 -u，避免 PYTHONPATH 等環境變數未設時報錯

# ── 路徑設定 ─────────────────────────────────────────────────────
PROJ_DIR="$HOME/doublink-tester"
REPORTS_DIR="$PROJ_DIR/reports"
LOG_DIR="$REPORTS_DIR/logs"
TODAY=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/test_run_${TIMESTAMP}.log"
REPORT_DOCX="$REPORTS_DIR/doublink_test_report_${TODAY}.docx"
LATEST_DOCX="$REPORTS_DIR/doublink_test_report_latest.docx"
HTTP_PORT=8888
PYTHON=python3
PYTEST_TIMEOUT=900
NETEMU_URL="http://192.168.105.115:8080"
UE_PING_IP="10.10.10.1"            # tester ens19 對端（Doublinks UE）

# ── 顏色輸出 ─────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*" | tee -a "$LOG_FILE"; }
ok()   { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✓${NC} $*" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠${NC} $*" | tee -a "$LOG_FILE"; }
err()  { echo -e "${RED}[$(date '+%H:%M:%S')] ✗${NC} $*" | tee -a "$LOG_FILE"; }

# ── 確保目錄存在 ─────────────────────────────────────────────────
mkdir -p "$REPORTS_DIR" "$LOG_DIR"

# ── 啟動記錄 ─────────────────────────────────────────────────────
echo "============================================================" >> "$LOG_FILE"
echo "  Doublink 每日自動測試  |  $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "============================================================" >> "$LOG_FILE"

cd "$PROJ_DIR"

# ── Step 1: git pull ──────────────────────────────────────────────
log "Step 1/8: git pull 最新程式碼..."
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
git pull --ff-only 2>&1 | tee -a "$LOG_FILE" || warn "git pull 失敗，繼續使用現有版本"
ok "程式碼版本: $(git log --oneline -1)"

# ── Step 2: 清除舊的 allure results（保留 history 供 TREND 使用）──────────
log "Step 2/8: 清除舊的 allure-results（保留 history 供 TREND 使用）..."

# 先把上次報告的 history 備份出來
HISTORY_BACKUP="/tmp/allure-history-backup-$$"
HISTORY_SAVED=false
if [ -d "$PROJ_DIR/allure-report/history" ]; then
  cp -r "$PROJ_DIR/allure-report/history" "$HISTORY_BACKUP"
  HISTORY_SAVED=true
  log "  → allure-report/history/ 已備份至 $HISTORY_BACKUP"
else
  warn "  → 無先前 history，TREND 將從本次開始累積"
fi

rm -rf "$PROJ_DIR/allure-results"
mkdir -p "$PROJ_DIR/allure-results"

# 把 history 放回 allure-results/history/，讓 allure generate 讀到
if [ "$HISTORY_SAVED" = true ]; then
  cp -r "$HISTORY_BACKUP" "$PROJ_DIR/allure-results/history"
  rm -rf "$HISTORY_BACKUP"
  ok "allure-results 已清除，history 已還原（TREND 可累積）"
else
  ok "allure-results 已清除（首次執行，無 history）"
fi

# ── Step 3: NetEmu bridge 健康檢查（若 DOWN 自動重建）────────────
# NetEmu service 重啟或 VM 重開機後，kernel-level bridge 不會自動帶回來。
# 沒有 bridge → wan_a_in/wan_b_in 收到的封包不會 forward 到 lan_a_out/lan_b_out
# → tester 整個測試環境連通中斷。
# 這一步在 pytest 之前確保 bridge 處於 forwarding 狀態。
log "Step 3/8: 檢查 NetEmu bridge 狀態..."

check_netemu_bridge_up() {
  # 回傳 "UP"、"DOWN"、或 "ERROR"
  curl -sL -m 5 "$NETEMU_URL/api/interfaces/" 2>/dev/null \
    | $PYTHON -c '
import sys, json
try:
    data = json.load(sys.stdin)
    bridges = [i for i in data if i["name"].startswith("br_netemu_")]
    if not bridges:
        print("DOWN")  # 沒有 bridge 物件存在
    elif all(b["state"] == "UP" for b in bridges):
        print("UP")
    else:
        print("DOWN")
except Exception:
    print("ERROR")
' 2>/dev/null
}

BRIDGE_STATE=$(check_netemu_bridge_up)
case "$BRIDGE_STATE" in
  UP)
    ok "NetEmu bridge 兩條 line 都 UP"
    ;;
  DOWN)
    warn "NetEmu bridge 未就緒，嘗試重建 ..."
    REBUILD_RESP=$(curl -sL -m 10 -X POST "$NETEMU_URL/api/rules/bridge" \
      -H 'Content-Type: application/json' \
      -d '{"lines":[{"downlink":"wan_a_in","uplink":"lan_a_out"},{"downlink":"wan_b_in","uplink":"lan_b_out"}]}' \
      -w 'HTTP_%{http_code}' 2>&1)
    log "  → 重建回應: $(echo "$REBUILD_RESP" | tail -c 200)"
    sleep 3
    if [ "$(check_netemu_bridge_up)" = "UP" ]; then
      ok "NetEmu bridge 重建成功"
    else
      err "NetEmu bridge 重建失敗 — 測試會大量 fail，但仍繼續執行"
    fi
    ;;
  ERROR|*)
    warn "無法連到 NetEmu API ($NETEMU_URL)，跳過 bridge 檢查（測試可能失敗）"
    ;;
esac

# 額外驗證：tester 是否能 ping 到 Doublinks UE — 若不通 NetworkManager 還沒拿到 DHCP
if ping -c 2 -W 2 "$UE_PING_IP" &>/dev/null; then
  ok "Doublinks UE ($UE_PING_IP) 可達"
else
  warn "Doublinks UE ($UE_PING_IP) 不可達 — UE 設備本身可能有問題（非 NetEmu）"
fi

# ── Step 4: 執行 pytest ───────────────────────────────────────────
log "Step 4/8: 執行全套測試（74 項，預計 ~3.5 小時）..."
PYTEST_EXIT=0
PYTHONPATH="$PROJ_DIR/src:${PYTHONPATH:-}" \
$PYTHON -m pytest \
  tests/test_mode_switching/ \
  tests/test_degradation/ \
  tests/test_golden_scenarios/ \
  tests/test_link_weight/ \
  -v \
  --timeout=$PYTEST_TIMEOUT \
  --alluredir="$PROJ_DIR/allure-results" \
  --tb=short \
  --continue-on-collection-errors \
  2>&1 | tee -a "$LOG_FILE" || PYTEST_EXIT=$?

# 解析測試結果
PASSED=$(grep -oP '\d+(?= passed)' "$LOG_FILE" | tail -1 || true)
FAILED=$(grep -oP '\d+(?= failed)' "$LOG_FILE" | tail -1 || true)
PASSED=${PASSED:-0}
FAILED=${FAILED:-0}
TOTAL=$(( PASSED + FAILED ))

if [ "$PYTEST_EXIT" -eq 0 ]; then
  ok "pytest 完成：${PASSED}/${TOTAL} PASSED"
else
  err "pytest 結束碼 $PYTEST_EXIT：${PASSED} passed, ${FAILED} failed"
fi

# ── Step 5: 生成 Allure HTML 報告 ────────────────────────────────
log "Step 5/8: 生成 Allure HTML 報告..."
if command -v allure &>/dev/null; then
  allure generate "$PROJ_DIR/allure-results" \
    -o "$PROJ_DIR/allure-report" \
    --clean 2>&1 | tee -a "$LOG_FILE"
  ok "Allure HTML 報告已生成：allure-report/"

  # 修剪 history JSON 檔避免長期無上限累積（保留最近 90 次 run）。
  # 此步驟在 generate 之後做，所以下次 Step 2 備份到的 history 就是已修剪的版本。
  HISTORY_KEEP=90
  log "  修剪 allure-report/history/ 保留最近 ${HISTORY_KEEP} 次 run ..."
  $PYTHON "$PROJ_DIR/scripts/prune_allure_history.py" \
    "$PROJ_DIR/allure-report/history" "$HISTORY_KEEP" 2>&1 | tee -a "$LOG_FILE" \
    || warn "history 修剪失敗（不影響本次報告）"
else
  warn "allure 未安裝，跳過 HTML 報告生成"
  warn "安裝方式：sudo apt-get install default-jre-headless && wget .../allure-2.29.0.tgz"
fi

# ── Step 6: 生成 Word 報告 ────────────────────────────────────────
log "Step 6/8: 生成 Word 測試報告..."
WORD_EXIT=0
PYTHONPATH="$PROJ_DIR/src:${PYTHONPATH:-}" \
$PYTHON scripts/generate_test_report.py \
  "$PROJ_DIR/allure-results" \
  "$REPORT_DOCX" 2>&1 | tee -a "$LOG_FILE" || WORD_EXIT=$?

if [ "$WORD_EXIT" -eq 0 ]; then
  # 同時建立 latest 連結方便固定 URL 存取
  cp "$REPORT_DOCX" "$LATEST_DOCX"
  DOCX_SIZE=$(du -sh "$REPORT_DOCX" | cut -f1)
  ok "Word 報告：$(basename $REPORT_DOCX)（$DOCX_SIZE）"
else
  err "Word 報告生成失敗（exit $WORD_EXIT）"
fi

# ── Step 7: 啟動/重啟 HTTP server ────────────────────────────────
log "Step 7/8: 重啟 HTTP 報告伺服器（port $HTTP_PORT）..."

# 停止舊的 http server
pkill -f "http.server $HTTP_PORT" 2>/dev/null || true
sleep 1

# 準備 HTTP 根目錄（包含 allure-report 和 Word 下載）
HTTP_ROOT="$PROJ_DIR/allure-report"
if [ -d "$HTTP_ROOT" ]; then
  # 複製 Word 報告到 allure-report 目錄，方便從同一頁面下載
  cp "$LATEST_DOCX" "$HTTP_ROOT/doublink_test_report_latest.docx" 2>/dev/null || true
  cp "$REPORT_DOCX" "$HTTP_ROOT/$(basename $REPORT_DOCX)" 2>/dev/null || true

  # 生成首頁 index.html（若 allure 沒蓋掉的話）
  cat > "$HTTP_ROOT/download.html" << HTMLEOF
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Doublink 測試報告下載</title>
<style>body{font-family:sans-serif;max-width:600px;margin:50px auto;padding:20px}
h1{color:#1F497D}a{display:block;margin:10px 0;padding:12px 20px;
background:#2E75B6;color:white;text-decoration:none;border-radius:6px;font-size:16px}
a:hover{background:#1F497D}.meta{color:#666;font-size:13px;margin-top:20px}</style>
</head><body>
<h1>📊 Doublink ATSSS 測試報告</h1>
<p>測試日期：$TODAY | 結果：${PASSED}/${TOTAL} PASSED</p>
<a href="index.html">🌐 Allure HTML 互動報告</a>
<a href="doublink_test_report_latest.docx" download>📄 Word 測試報告（最新版）</a>
<a href="$(basename $REPORT_DOCX)" download>📄 Word 測試報告（${TODAY}）</a>
<div class="meta">更新時間：$(date '+%Y-%m-%d %H:%M:%S')</div>
</body></html>
HTMLEOF
  ok "download.html 已生成"
fi

# 啟動 HTTP server（背景執行）
if [ -d "$HTTP_ROOT" ]; then
  cd "$HTTP_ROOT"
  nohup $PYTHON -m http.server $HTTP_PORT \
    --bind 0.0.0.0 \
    >> "$LOG_DIR/http_server.log" 2>&1 &
  HTTP_PID=$!
  echo "$HTTP_PID" > "$PROJ_DIR/.http_server.pid"
  sleep 2
  if kill -0 "$HTTP_PID" 2>/dev/null; then
    ok "HTTP server 啟動成功 (PID=$HTTP_PID)"
    ok "報告網址：http://192.168.105.210:${HTTP_PORT}/"
    ok "下載頁面：http://192.168.105.210:${HTTP_PORT}/download.html"
  else
    err "HTTP server 啟動失敗"
  fi
  cd "$PROJ_DIR"
else
  warn "allure-report 目錄不存在，HTTP server 未啟動"
  warn "Word 報告位置：$REPORT_DOCX"
fi

# ── Step 8: Auto-switch vs 固定模式比較（Group B 網路劣化，同 seed）────────
# NetEmu variation 已用 NETEMU_VARIATION_SEED 鎖定 → 每個劣化條件重播「完全相同」
# 的劣化,所以這一輪 auto-switch 與上面每日固定模式跑的劣化一致,可公平對照。
# 只跑 Group B（網路劣化）條件;失敗不影響每日測試結果。
log "Step 8/8: Auto-switch vs 固定模式比較（Group B 網路劣化，seed 鎖定）..."
AB_MD="$REPORTS_DIR/autoswitch_${TODAY}.md"
AB_JSON="$REPORTS_DIR/autoswitch_${TODAY}.json"
AB_EXIT=0
PYTHONPATH="$PROJ_DIR/src:${PYTHONPATH:-}" \
$PYTHON scripts/run_autoswitch_degradation.py \
  --duration 120 \
  --output "$AB_JSON" \
  --report "$AB_MD" 2>&1 | tee -a "$LOG_FILE" || AB_EXIT=$?
if [ "$AB_EXIT" -eq 0 ]; then
  ok "Auto-switch 比較完成：$(basename $AB_MD)"
  [ -d "$HTTP_ROOT" ] && cp "$AB_MD" "$HTTP_ROOT/" 2>/dev/null || true
else
  warn "Auto-switch 比較失敗（exit $AB_EXIT，不影響每日測試結果）"
fi

# ── 保留最近 30 天的 log 和報告 ──────────────────────────────────
find "$LOG_DIR" -name "test_run_*.log" -mtime +30 -delete 2>/dev/null || true
find "$REPORTS_DIR" -name "doublink_test_report_*.docx" -mtime +30 -delete 2>/dev/null || true
find "$REPORTS_DIR" -name "autoswitch_*.md" -mtime +30 -delete 2>/dev/null || true
find "$REPORTS_DIR" -name "autoswitch_*.json" -mtime +30 -delete 2>/dev/null || true
ok "舊日誌清理完成（保留 30 天）"

# ── 結束摘要 ─────────────────────────────────────────────────────
echo "" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"
echo "  測試完成：$(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "  結果：${PASSED}/${TOTAL} PASSED，${FAILED} FAILED" | tee -a "$LOG_FILE"
echo "  報告：http://192.168.105.210:${HTTP_PORT}/download.html" | tee -a "$LOG_FILE"
echo "  日誌：$LOG_FILE" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"

exit $PYTEST_EXIT
