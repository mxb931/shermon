# SherMon (MVP)

Real-time monitoring service for SherMon incidents.

## What is implemented

- FastAPI backend with authenticated ingest endpoint.
- SQLAlchemy persistence for incident history and current status.
- Status projection to green/yellow/red/purple/white.
- WebSocket updates for live dashboard refresh.
- Dashboard tabs for Alerts, Acknowledgements, Test Sender, and Help.
- Hierarchical Alerts drill-down (Stores -> Components -> Active Alerts) with in-place navigation.
- Store/component status buttons colored by highest active severity precedence.
- Green-reset behavior: incoming green/OK signals clear existing active alerts for red/yellow/purple components.
- Java sender helper class for Xstore integration.

## Run locally

From `deploy` directory:

```bash
docker compose up
```

This starts three services:

- `mysql` (persistent local MySQL)
- `api` (FastAPI on MySQL)
- `dashboard` (frontend + local reverse proxy for `/api/*` and `/ws/updates`)

Then open:

- Dashboard: http://localhost:8080
- API docs (backend): http://localhost:8000/docs

## Send test event

```bash
curl -X POST "http://localhost:8000/api/v1/events" \
  -H "Content-Type: application/json" \
  -H "X-Monitor-Key: dev-monitor-key" \
  -d '{
    "event_id": "evt-local-1",
    "dedup_key": "PAYMENT_GATEWAY_TIMEOUT",
    "store_id": "store-104",
    "component": "payments",
    "category": "external_dependency",
    "event_type": "problem",
    "severity": "critical",
    "message": "Gateway timeout after 2 retries",
    "source": "test-sender",
    "happened_at": "2026-03-20T15:11:00Z",
    "metadata": {"terminal_id": "lane-3"}
  }'
```

## One-command smoke test

Run this from the backend directory:

```bash
bash tests/run_smoke.sh
```

What it does:

- Ensures a virtual environment exists.
- Starts the API on `127.0.0.1:8000`.
- Uses an isolated temporary SQLite database for the run (local test only; Rancher deploy targets MySQL).
- Runs `tests/smoke_test.py` and prints pass/fail results.
- Stops the API automatically.

## One-time SQLite -> MySQL migration

If you have historical data in a SQLite database and need to copy it once into MySQL:

1. Ensure MySQL target schema is available by starting the app once against your MySQL URL.
2. Run a dry-run to verify row counts:

```bash
cd backend
python scripts/migrate_sqlite_to_mysql.py \
  --source sqlite:////absolute/path/to/monitor.db \
  --target "mysql+pymysql://<user>:<password>@<host>:3306/<database>?charset=utf8mb4" \
  --dry-run
```

3. Run the actual migration (default behavior truncates target tables before copy):

```bash
cd backend
python scripts/migrate_sqlite_to_mysql.py \
  --source sqlite:////absolute/path/to/monitor.db \
  --target "mysql+pymysql://<user>:<password>@<host>:3306/<database>?charset=utf8mb4"
```

Optional flags:

- `--no-truncate` to append without clearing target tables first.
- `--batch-size 1000` to tune insert batching.

## API usage docs

- Developer usage guide: `docs/api/developer-usage.md`
- Contract reference: `docs/api/monitoring-events-v1.md`

## Next implementation targets

- Add PostgreSQL migration path and retention jobs.
- Add integration tests and load testing harness.
- Introduce shared scheduler/worker for timeout and ack expiry sweepers.
