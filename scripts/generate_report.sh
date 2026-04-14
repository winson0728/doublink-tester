#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if [ ! -d allure-results ] || [ -z "$(ls -A allure-results 2>/dev/null)" ]; then
  echo "No test results found in allure-results/"
  echo "Run tests first: ./scripts/run_tests.sh"
  exit 1
fi

allure generate allure-results -o allure-report --clean
echo "Report generated at: allure-report/index.html"
echo ""
echo "To serve the report:"
echo "  allure serve allure-results"
