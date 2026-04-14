#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Activate venv
source .venv/bin/activate 2>/dev/null || true

# Parse arguments
CATEGORY="${1:---all}"
REPORT_FLAG="${2:-}"

# Clean previous results
rm -rf allure-results/*

# Build pytest args based on category
case "$CATEGORY" in
  --all)           PYTEST_ARGS="tests/" ;;
  mode_switching)  PYTEST_ARGS="tests/test_mode_switching/" ;;
  link_weight)     PYTEST_ARGS="tests/test_link_weight/" ;;
  degradation)     PYTEST_ARGS="tests/test_degradation/" ;;
  app_layer)       PYTEST_ARGS="tests/test_app_layer/" ;;
  integration)     PYTEST_ARGS="tests/test_integration/" ;;
  *)               PYTEST_ARGS="$CATEGORY" ;;
esac

echo "Running tests: $PYTEST_ARGS"
pytest $PYTEST_ARGS \
  --alluredir=allure-results \
  -v \
  --tb=short \
  --timeout=300

if [ "$REPORT_FLAG" = "--report" ]; then
  allure generate allure-results -o allure-report --clean
  echo "Report generated at allure-report/index.html"
fi
