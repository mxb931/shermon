# SherMon (MVP)

Real-time monitoring service for Xstore incidents.

## What is implemented

- FastAPI backend with authenticated ingest endpoint.
- SQLite persistence for incident history and current status.
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

Then open:

- Dashboard: http://localhost:8080
- API docs: http://localhost:8000/docs
- OpenAPI Swagger UI (frontend): http://localhost:8080/api-swagger.html

## Rancher deployment (SQLite-first)

First release deployment uses a single image (frontend + backend on one origin),
SQLite on a persistent volume, and one app replica.

Required runtime env for deployment:

- `MONITOR_API_KEY` (must be set; app returns 503 on auth endpoints if missing)
- `MONITOR_DATABASE_URL=sqlite:////data/monitor/monitor.db`

Recommended first-release constraints:

- Run exactly one replica.
- Mount persistent storage at `/data/monitor`.
- Use Rancher/stdout logging for operations.

Build image from repo root:

```bash
sh ./docker_build.sh
```

### Rancher apply/update runbook

1. Edit deployment template:

- Set image name in `deploy/rancher-sqlite-single-image.yaml` (`your-registry/xstore-monitor:latest`).
- Set ingress host in `deploy/rancher-sqlite-single-image.yaml` (`xstore-monitor.example.com`).
- Set `MONITOR_CORS_ALLOW_ORIGINS` to your deployed HTTPS origin.

2. Edit the secret file (never commit this to git):

- Copy it if needed: `cp deploy/rancher-secret.yaml.example deploy/rancher-secret.yaml`
- Set `MONITOR_API_KEY` to a strong random value: `openssl rand -hex 32`
- `deploy/rancher-secret.yaml` is in `.gitignore` — keep it that way.

3. Sanity-check manifests before apply:

```bash
kubectl apply --dry-run=client -f deploy/rancher-secret.yaml
kubectl apply --dry-run=client -f deploy/rancher-sqlite-single-image.yaml
kubectl diff -f deploy/rancher-sqlite-single-image.yaml || true
```

Quick checklist:

- `image:` points to your pushed tag.
- ingress `host:` matches your DNS.
- secret value is replaced and `rancher-secret.yaml` is not staged in git.
- PVC storage size/class match your cluster policy.
- replicas remain `1` for SQLite-first rollout.

5. Build and push image (example):

```bash
IMAGE_NAME=xstore-monitor IMAGE_TAG=v1 REGISTRY_IMAGE=your-registry/xstore-monitor sh ./docker_build.sh
```

4. Apply first deployment (secret first, then main manifest):

```bash
kubectl apply -f deploy/rancher-secret.yaml
kubectl apply -f deploy/rancher-sqlite-single-image.yaml
kubectl -n xstore-monitor rollout status deploy/xstore-monitor
```

6. Update to a new image tag:

```bash
kubectl -n xstore-monitor set image deploy/xstore-monitor app=your-registry/xstore-monitor:v2
kubectl -n xstore-monitor rollout status deploy/xstore-monitor
```

7. Check runtime state:

```bash
kubectl -n xstore-monitor get pods,svc,ingress,pvc
kubectl -n xstore-monitor logs deploy/xstore-monitor --tail=200
```

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
- OpenAPI spec (canonical): `docs/api/monitoring-events-v1.openapi.yaml`
- OpenAPI shared components: `docs/api/monitoring-events-v1.components.yaml`
- Frontend docs sync script: `scripts/sync_openapi_docs.sh`
- Generated TypeScript API types: `frontend/docs/api/generated/monitoring-events-v1.types.ts`

## Next implementation targets

- Add PostgreSQL migration path and retention jobs.
- Add integration tests and load testing harness.
- Introduce shared scheduler/worker for timeout and ack expiry sweepers.
