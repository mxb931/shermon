# Monitoring Events API v1

## Authentication

Use header `X-Monitor-Key` with the shared key.

## POST /api/v1/events

Accepts one event from Xstore.

### Request payload

```json
{
  "event_id": "evt-20260320-001",
  "dedup_key": "PAYMENT_GATEWAY_TIMEOUT",
  "store_id": "store-104",
  "component": "payments",
  "category": "external_dependency",
  "event_type": "problem",
  "severity": "critical",
  "message": "Gateway timeout after 2 retries",
  "source": "xstore-pos",
  "happened_at": "2026-03-20T15:11:00Z",
  "metadata": {
    "terminal_id": "lane-3",
    "order_id": "A12810"
  }
}
```

### Event fields

- `event_id`: unique identifier per emitted event.
- `dedup_key`: groups repeated failures for deduplication.
- `store_id`: store identifier.
- `component`: monitored component name.
- `category`: event grouping.
- `event_type`: `problem` or `recovery`.
- `severity`: `info`, `warning`, `critical`.
- `message`: operator-readable summary.
- `source`: emitter name in Xstore.
- `happened_at`: UTC ISO8601 timestamp.
- `metadata`: optional key-value context map.

### Response payload

```json
{
  "accepted": true,
  "deduplicated": false,
  "sequence": 27
}
```

## GET /api/v1/bootstrap

Returns latest sequence, current entity statuses, and recent events for dashboard bootstrap.

## GET /api/v1/summary

Returns counts by color state.

## WebSocket /ws/updates

Pushes payloads with:
- `kind`: `event_update`
- `sequence`: monotonic integer
- `event`: normalized event payload
- `status`: latest entity status snapshot
- `deduplicated`: whether event was deduplicated on ingest
