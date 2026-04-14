#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

source .venv/bin/activate 2>/dev/null || true

echo "Starting Doublink Tester Control API on http://0.0.0.0:8090"
uvicorn doublink_tester.api.app:create_app \
  --factory \
  --host 0.0.0.0 \
  --port 8090 \
  --log-level info \
  --reload
