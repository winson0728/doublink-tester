#!/usr/bin/env bash
set -euo pipefail

echo "=== Doublink Tester — Ubuntu Desktop Installation ==="

# System dependencies
sudo apt-get update
sudo apt-get install -y \
  python3.12 python3.12-venv python3-pip \
  iperf3 docker.io docker-compose-v2 curl wget

# Fortio
if ! command -v fortio &>/dev/null; then
  echo "Installing fortio..."
  curl -L https://github.com/fortio/fortio/releases/download/v1.63.5/fortio_linux_amd64-1.63.5.tgz \
    | sudo tar xz -C /usr/local/bin fortio
fi

# SIPp (optional)
if ! command -v sipp &>/dev/null; then
  echo "Installing SIPp..."
  sudo apt-get install -y sip-tester || echo "SIPp not available in repos — install manually if needed"
fi

# Allure
if ! command -v allure &>/dev/null; then
  echo "Installing Allure..."
  sudo apt-get install -y default-jre
  curl -L https://github.com/allure-framework/allure2/releases/download/2.27.0/allure-2.27.0.tgz \
    | sudo tar xz -C /opt/
  sudo ln -sf /opt/allure-2.27.0/bin/allure /usr/local/bin/allure
fi

# Python environment
cd "$(dirname "$0")/.."
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

# Environment config
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from template — please edit with your API keys"
fi

# Docker services
cd deploy
docker compose up -d prometheus pushgateway grafana

echo ""
echo "=== Installation complete ==="
echo "  Activate env:  source .venv/bin/activate"
echo "  Run tests:     ./scripts/run_tests.sh"
echo "  Start API:     ./scripts/run_api.sh"
echo "  Grafana:       http://localhost:3000 (admin/admin)"
echo "  Prometheus:    http://localhost:9090"
