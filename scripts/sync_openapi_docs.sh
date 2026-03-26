#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$ROOT_DIR/docs/api"
DST_DIR="$ROOT_DIR/frontend/docs/api"

cp "$SRC_DIR/monitoring-events-v1.openapi.yaml" "$DST_DIR/monitoring-events-v1.openapi.yaml"
cp "$SRC_DIR/monitoring-events-v1.components.yaml" "$DST_DIR/monitoring-events-v1.components.yaml"
cp "$SRC_DIR/monitoring-events-v1.md" "$DST_DIR/monitoring-events-v1.md"

echo "Synced OpenAPI docs to frontend/docs/api"
