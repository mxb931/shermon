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

SMOKE_PORT="$(python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
  s.bind(("127.0.0.1", 0))
  print(s.getsockname()[1])
PY
)"
export SMOKE_BASE="http://127.0.0.1:${SMOKE_PORT}"

.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$SMOKE_PORT" >/tmp/shermon-smoke.log 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

for _ in {1..30}; do
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    echo "Smoke server exited unexpectedly"
    cat /tmp/shermon-smoke.log
    exit 1
  fi
  if curl -s "$SMOKE_BASE/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -s "$SMOKE_BASE/health" >/dev/null 2>&1; then
  echo "Smoke server did not become ready at $SMOKE_BASE"
  cat /tmp/shermon-smoke.log
  exit 1
fi

python3 tests/smoke_test.py
