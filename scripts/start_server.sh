#!/usr/bin/env sh
set -eu

# Resolve repo root relative to this script so it can be run from anywhere.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT/backend"

VENV_PYTHON="$REPO_ROOT/.venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Missing virtual environment at $REPO_ROOT/.venv"
  echo "Create it first, for example: python3 -m venv .venv"
  exit 1
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

exec "$VENV_PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT"