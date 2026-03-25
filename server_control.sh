#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$ROOT_DIR/deploy"

usage() {
  cat <<'USAGE'
Usage: ./server_control.sh <start|stop|restart>

Commands:
  start    Start SherMon services (API + dashboard)
  stop     Stop SherMon services
  restart  Stop then start SherMon services
USAGE
}

validate_environment() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker is not installed or not in PATH."
    exit 1
  fi

  if [[ ! -d "$DEPLOY_DIR" ]]; then
    echo "Error: deploy directory not found at $DEPLOY_DIR"
    exit 1
  fi

  if [[ ! -f "$DEPLOY_DIR/docker-compose.yml" ]]; then
    echo "Error: docker-compose.yml not found in $DEPLOY_DIR"
    exit 1
  fi
}

start_services() {
  echo "Starting SherMon services..."
  docker compose up -d
  echo
  echo "Current service status:"
  docker compose ps
  echo
  echo "Startup complete."
  echo "Dashboard: http://localhost:8080"
  echo "API docs:  http://localhost:8000/docs"
}

stop_services() {
  echo "Stopping SherMon services..."
  docker compose down
  echo
  echo "Current service status:"
  docker compose ps
  echo
  echo "Shutdown complete."
}

main() {
  if [[ $# -ne 1 ]]; then
    usage
    exit 1
  fi

  validate_environment
  cd "$DEPLOY_DIR"

  case "$1" in
    start)
      start_services
      ;;
    stop)
      stop_services
      ;;
    restart)
      stop_services
      echo
      start_services
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      echo "Error: unknown command '$1'"
      echo
      usage
      exit 1
      ;;
  esac
}

main "$@"