# SherMon API Developer Usage Guide

This guide explains how to use the API in plain language.

## Keep This Guide In Sync

If the API contract changes, update this document in the same pull request.

When changing any API field or behavior, update:

- Request/response examples in this file.
- Field tables in this file.
- `docs/api/monitoring-events-v1.md`.
- `backend/tests/smoke_test.py` test payloads/assertions.

## Base URL

Local default:

- `http://127.0.0.1:8000`

## Authentication

Event ingest and acknowledgement write endpoints require auth.

Send this header on:

- `POST /api/v1/events`
- `POST /api/v1/acks`
- `DELETE /api/v1/acks/{event_id}`

Header:

- `X-Monitor-Key: <your-api-key>`

Default local key (if not overridden by env var):

- `dev-monitor-key`

## Quick Start

### 1) Send a problem event

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/events" \
  -H "Content-Type: application/json" \
  -H "X-Monitor-Key: dev-monitor-key" \
  -d '{
    "event_id": "evt-demo-1001",
    "dedup_key": "PAY_TIMEOUT_DEMO",
    "store_id": "store-104",
    "component": "payments",
    "event_type": "problem",
    "severity": "critical",
    "message": "Gateway timeout after retries",
    "source": "xstore-pos",
    "metadata": {
      "terminal_id": "lane-3"
    }
  }'
```

Typical response:

```json
{
  "accepted": true,
  "deduplicated": false,
  "sequence": 12
}
```

### 2) Send a recovery event

Use the same `dedup_key` to close that active issue:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/events" \
  -H "Content-Type: application/json" \
  -H "X-Monitor-Key: dev-monitor-key" \
  -d '{
    "event_id": "evt-demo-1002",
    "dedup_key": "PAY_TIMEOUT_DEMO",
    "store_id": "store-104",
    "component": "payments",
    "event_type": "recovery",
    "severity": "info",
    "message": "Gateway recovered",
    "source": "xstore-pos",
    "metadata": {}
  }'
```

## Java Copy/Paste Examples

These examples match the current helper at `xstore-integration/java/MonitorClient.java`.

### 1) Create the client

```java
MonitorClient client = new MonitorClient(
    "http://127.0.0.1:8000/api/v1/events",
    "dev-monitor-key"
);
```

### 2) Send a problem event (raw JSON string)

```java
String problemEventJson = """
{
  "event_id": "evt-java-problem-1001",
  "dedup_key": "PAY_TIMEOUT_JAVA_DEMO",
  "store_id": "store-104",
  "component": "payments",
  "event_type": "problem",
  "severity": "critical",
  "message": "Gateway timeout after retries",
  "source": "xstore-pos",
  "metadata": {"terminal_id": "lane-3"}
}
""";

boolean posted = client.postEvent(problemEventJson);
System.out.println("Problem event posted: " + posted);
```

### 3) Send a recovery event (same dedup key)

```java
String recoveryEventJson = """
{
  "event_id": "evt-java-recovery-1002",
  "dedup_key": "PAY_TIMEOUT_JAVA_DEMO",
  "store_id": "store-104",
  "component": "payments",
  "event_type": "recovery",
  "severity": "info",
  "message": "Gateway recovered",
  "source": "xstore-pos",
  "metadata": {}
}
""";

boolean recovered = client.postEvent(recoveryEventJson);
System.out.println("Recovery event posted: " + recovered);
```

### 4) Full minimal runnable Java example

```java
import com.xstore.monitor.MonitorClient;

public class MonitorExample {
    public static void main(String[] args) throws Exception {
        MonitorClient client = new MonitorClient(
                "http://127.0.0.1:8000/api/v1/events",
                "dev-monitor-key"
        );

        String problemEventJson = """
        {
          "event_id": "evt-java-problem-1001",
          "dedup_key": "PAY_TIMEOUT_JAVA_DEMO",
          "store_id": "store-104",
          "component": "payments",
          "event_type": "problem",
          "severity": "critical",
          "message": "Gateway timeout after retries",
          "source": "xstore-pos",
          "metadata": {"terminal_id": "lane-3"}
        }
        """;

        String recoveryEventJson = """
        {
          "event_id": "evt-java-recovery-1002",
          "dedup_key": "PAY_TIMEOUT_JAVA_DEMO",
          "store_id": "store-104",
          "component": "payments",
          "event_type": "recovery",
          "severity": "info",
          "message": "Gateway recovered",
          "source": "xstore-pos",
          "metadata": {}
        }
        """;

        System.out.println("Problem posted: " + client.postEvent(problemEventJson));
        System.out.println("Recovery posted: " + client.postEvent(recoveryEventJson));
    }
}
```

## Endpoints

## `GET /health`

Simple service check.

Response:

```json
{ "status": "ok" }
```

No auth required.

---

## `POST /api/v1/events`

Ingest one event.

Auth required: `X-Monitor-Key` header.

### Request fields

All fields are required unless noted.

| Field | Type | Required | Rules / Allowed Values | Default |
|---|---|---|---|---|
| `event_id` | string | Yes | Unique per event, length 6-64 | None |
| `dedup_key` | string | Yes | Groups repeated incidents, length 3-128 | None |
| `store_id` | string | Yes | Length 1-64 | None |
| `component` | string | Yes | Length 1-128 | None |
| `event_type` | string | Yes | `problem`, `recovery`, `disable`, or `enable` | None |
| `severity` | string | Yes | `info`, `warning`, `critical` | None |
| `message` | string | Yes | Length 1-4000 | None |
| `source` | string | Yes | Length 1-128 | None |
| `expected_green_interval_seconds` | integer | No | Minimum 1; enables purple timeout when missed | None |
| `expires_at` | datetime string | No | Must be in the future if provided | None |
| `metadata` | object | No | Free-form key/value map | `{}` |

### Behavior notes

- `problem` events:
  - `critical` sets status color to `red`
  - `warning` sets status color to `yellow`
  - `info` sets status color to `green`
- `recovery` events set status color to `green`.
- `disable` events set status to `white` and suppress timeout evaluation.
- `enable` events set status to `green` and resume timeout evaluation.
- If an incoming event resolves to `green` while the component is currently `red`, `yellow`, or `purple`, all active alerts for that component are cleared and status resets to `green`.
- If `expected_green_interval_seconds` is set and green check-ins are missed, status transitions to `purple`.
- Repeated active `problem` with same `store_id + component + dedup_key` is treated as deduplicated.
- If you resend the exact same `event_id`, it is treated as idempotent replay.
- If `expires_at` is in the past, API returns `422`.
- `happened_at` is stamped automatically by the API at ingest time.

### Response fields

| Field | Type | Meaning |
|---|---|---|
| `accepted` | boolean | Event was accepted by API |
| `deduplicated` | boolean | Event was deduplicated |
| `sequence` | integer or null | Monotonic stream sequence; can be `null` on exact `event_id` replay |

Example idempotent replay response:

```json
{
  "accepted": true,
  "deduplicated": true,
  "sequence": null
}
```

### Common errors

- `401 Unauthorized`:
  - Missing or invalid `X-Monitor-Key`
- `422 Unprocessable Entity`:
  - Validation error (missing field, bad enum value, length violation, bad datetime)

---

## `GET /api/v1/bootstrap`

Returns initial dashboard data.

No auth required.

Response shape:

```json
{
  "latest_sequence": 42,
  "statuses": [
    {
      "store_id": "store-104",
      "component": "payments",
      "status_color": "red",
      "active_incident_count": 1,
      "last_message": "Gateway timeout",
      "last_event_id": "evt-demo-1001",
      "last_changed_at": "2026-03-20T15:11:00"
    }
  ],
  "recent_events": [
    {
      "event_id": "evt-demo-1001",
      "dedup_key": "PAY_TIMEOUT_DEMO",
      "store_id": "store-104",
      "component": "payments",
      "event_type": "problem",
      "severity": "critical",
      "message": "Gateway timeout after retries",
      "source": "xstore-pos",
      "happened_at": "2026-03-20T15:11:00",
      "active": true
    }
  ]
}
```

Notes:

- `recent_events` max size defaults to 200 (configurable via `MONITOR_RECENT_EVENT_LIMIT`).
- `status_color` values are `green`, `yellow`, `red`, `purple`, `white`.

---

## `GET /api/v1/summary`

Returns simple color counts for status tiles.

No auth required.

Response:

```json
{
  "counts": {
    "green": 10,
    "yellow": 2,
    "red": 1,
    "purple": 0,
    "white": 0
  }
}
```

---

## `GET /api/v1/active-alerts`

Returns currently active incident events for one entity.

No auth required.

Query parameters:

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `store_id` | string | Yes | Exact store/entity identifier |
| `component` | string | Yes | Exact component within store |

Response: array of active incident events ordered newest first.

Example request:

```bash
curl "http://127.0.0.1:8000/api/v1/active-alerts?store_id=store-104&component=payments"
```

Example response:

```json
[
  {
    "event_id": "evt-demo-1001",
    "dedup_key": "PAY_TIMEOUT_DEMO",
    "store_id": "store-104",
    "component": "payments",
    "event_type": "problem",
    "severity": "critical",
    "message": "Gateway timeout after retries",
    "source": "xstore-pos",
    "happened_at": "2026-03-20T15:11:00",
    "active": true
  }
]
```

---

## `GET /api/v1/status/stores`

Returns store-level hierarchy rows used by the Alerts drill-down UI.

No auth required.

Response item fields:

| Field | Type | Notes |
|---|---|---|
| `store_id` | string | Store identifier |
| `status_color` | string | Highest-priority component status in that store |
| `component_count` | integer | Number of known components for the store |
| `active_incident_count` | integer | Sum of active incidents across components |

Status precedence used for `status_color`:

1. `red` (critical)
2. `yellow` (warning)
3. `purple` (stale)
4. `green` (ok)
5. `white` (disabled)

---

## `GET /api/v1/status/stores/{store_id}/components`

Returns component-level hierarchy rows for one store.

No auth required.

Example request:

```bash
curl "http://127.0.0.1:8000/api/v1/status/stores/store-104/components"
```

---

## `GET /api/v1/acks`

Returns active acknowledgements.

No auth required.

---

## `POST /api/v1/acks`

Create or refresh an acknowledgement for an event.

Auth required: `X-Monitor-Key` header.

Request body:

| Field | Type | Required | Rules / Allowed Values |
|---|---|---|---|
| `event_id` | string | Yes | Must reference an existing event |
| `ack_message` | string | Yes | Length 1-4000 |
| `ack_by` | string | No | Length 1-128 |
| `expires_at` | datetime string | Yes | Must be in the future |

---

## `DELETE /api/v1/acks/{event_id}`

Expire an acknowledgement immediately.

Auth required: `X-Monitor-Key` header.

---

## `WS /ws/updates`

WebSocket stream for real-time updates.

No auth required in current MVP.

Each message has:

```json
{
  "kind": "event_update",
  "sequence": 43,
  "event": {
    "event_id": "evt-demo-1002",
    "dedup_key": "PAY_TIMEOUT_DEMO",
    "store_id": "store-104",
    "component": "payments",
    "event_type": "recovery",
    "severity": "info",
    "message": "Gateway recovered",
    "source": "xstore-pos",
    "happened_at": "2026-03-20T15:12:00",
    "active": false
  },
  "status": {
    "store_id": "store-104",
    "component": "payments",
    "status_color": "green",
    "active_incident_count": 0,
    "last_message": "Gateway recovered",
    "last_event_id": "evt-demo-1002",
    "last_changed_at": "2026-03-20T15:12:00"
  },
  "deduplicated": false
}
```

Additional websocket kinds:

- `ack_update`: contains `ack` payload with active acknowledgement state
- `ack_expired`: contains `event_id` of expired acknowledgement
- `status_timeout`: contains `status` when entity transitions to purple

## Environment Defaults

| Env Var | Purpose | Default |
|---|---|---|
| `MONITOR_API_KEY` | API key for event ingest auth | `dev-monitor-key` |
| `MONITOR_DATABASE_URL` | Database connection URL | `sqlite:///.../backend/monitor.db` |
| `MONITOR_RECENT_EVENT_LIMIT` | Max events in bootstrap response | `200` |

## Developer Tips

- Always generate a unique `event_id`.
- Keep `dedup_key` stable for the same underlying incident type.
- Emit a matching `recovery` when the issue clears.
- Use UTC timestamps for consistency.
