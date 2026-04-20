#!/usr/bin/env bash
# =============================================================================
# daily_test_run.sh — 每日自動測試 + 報告生成
#
# 排程：每日 04:00 由 cron 執行
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
log "Step 1/6: git pull 最新程式碼..."
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
git pull --ff-only 2>&1 | tee -a "$LOG_FILE" || warn "git pull 失敗，繼續使用現有版本"
ok "程式碼版本: $(git log --oneline -1)"

# ── Step 2: 清除舊的 allure results ─────────────────────────────
log "Step 2/6: 清除舊的 allure-results..."
rm -rf "$PROJ_DIR/allure-results"
mkdir -p "$PROJ_DIR/allure-results"
ok "allure-results 已清除"

# ── Step 3: 執行 pytest ───────────────────────────────────────────
log "Step 3/6: 執行全套測試（74 項，預計 ~30 分鐘）..."
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

# ── Step 4: 生成 Allure HTML 報告 ────────────────────────────────
log "Step 4/6: 生成 Allure HTML 報告..."
if command -v allure &>/dev/null; then
  allure generate "$PROJ_DIR/allure-results" \
    -o "$PROJ_DIR/allure-report" \
    --clean 2>&1 | tee -a "$LOG_FILE"
  ok "Allure HTML 報告已生成：allure-report/"
else
  warn "allure 未安裝，跳過 HTML 報告生成"
  warn "安裝方式：sudo apt-get install default-jre-headless && wget .../allure-2.29.0.tgz"
fi

# ── Step 5: 生成 Word 報告 ────────────────────────────────────────
log "Step 5/6: 生成 Word 測試報告..."
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

# ── Step 6: 啟動/重啟 HTTP server ────────────────────────────────
log "Step 6/6: 重啟 HTTP 報告伺服器（port $HTTP_PORT）..."

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

# ── 保留最近 30 天的 log 和報告 ──────────────────────────────────
find "$LOG_DIR" -name "test_run_*.log" -mtime +30 -delete 2>/dev/null || true
find "$REPORTS_DIR" -name "doublink_test_report_*.docx" -mtime +30 -delete 2>/dev/null || true
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
