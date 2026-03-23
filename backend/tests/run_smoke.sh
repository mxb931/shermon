#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$BACKEND_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

export MONITOR_DATABASE_URL="sqlite:////tmp/shermon-smoke-$(date +%s).db"
export MONITOR_API_KEY="dev-monitor-key"

.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/shermon-smoke.log 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

for _ in {1..30}; do
  if curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

python3 tests/smoke_test.py
