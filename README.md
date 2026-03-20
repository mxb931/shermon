# Xstore Monitor (MVP)

Xymon-inspired real-time monitoring service for Xstore incidents.

## What is implemented

- FastAPI backend with authenticated ingest endpoint.
- SQLite persistence for incident history and current status.
- Status projection to green/yellow/red.
- WebSocket updates for live dashboard refresh.
- Minimal dashboard showing summary, entity status tiles, and incident stream.
- Java sender helper class for Xstore integration.

## Run locally

From `deploy` directory:

```bash
docker compose up
```

Then open:

- Dashboard: http://localhost:8080
- API docs: http://localhost:8000/docs

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
    "source": "xstore-pos",
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
- Uses an isolated temporary SQLite database for the run.
- Runs `tests/smoke_test.py` and prints pass/fail results.
- Stops the API automatically.

## API usage docs

- Developer usage guide: `docs/api/developer-usage.md`
- Contract reference: `docs/api/monitoring-events-v1.md`

## Next implementation targets

- Add acknowledge and silence workflow.
- Add PostgreSQL migration path and retention jobs.
- Add integration tests and load testing harness.
