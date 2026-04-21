#!/usr/bin/env bash
# 啟動 Doublink Test Runner Web UI
# 使用方式：bash scripts/start_ui.sh [port]

PORT="${1:-9080}"
PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "========================================="
echo "  Doublink ATSSS Test Runner"
echo "  http://192.168.105.210:${PORT}/"
echo "========================================="

# 停止舊的 run_ui 程序
pkill -f "run_ui.py" 2>/dev/null || true
sleep 1

# 安裝依賴（若未安裝）
pip3 install fastapi uvicorn python-multipart --quiet 2>/dev/null

# 啟動
cd "$PROJ_DIR"
PYTHONPATH="$PROJ_DIR/src:${PYTHONPATH:-}" \
  python3 scripts/run_ui.py "$PORT"
