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
  "event_type": "problem",
  "severity": "critical",
  "message": "Gateway timeout after 2 retries",
  "source": "xstore-pos",
  "stale_interval": "2h",
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
- `event_type`: `problem`, `ok`, `disable`, or `enable`.
- `severity`: `info`, `warning`, `critical`.
- `message`: operator-readable summary.
- `source`: emitter name in Xstore.
- `happened_at`: stamped automatically by the API at ingest time.
- `stale_interval`: optional stale timeout duration using only `d`, `h`, and `m` units (for example `2d5h10m`, `4h`, `30m`). If omitted, timeout-to-purple is disabled.
- `metadata`: optional key-value context map.

Green reset behavior:

- If an incoming event resolves to green/OK while the component is currently `red`, `yellow`, or `purple`, SherMon clears all active incidents for that component and resets component status to `green`.

Severity rules by event type:

- `problem`: `warning` or `critical` only.
- `ok`: `info` only.
- `enable`: `info` only.
- `disable`: `info` only.
- Invalid event_type/severity combinations are rejected with `422`.

Active alert rule:

- Only `red`, `yellow`, or `purple` conditions are considered active alerts.
- `green` and `white` are not active alerts.

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

Color keys: `green`, `yellow`, `red`, `purple`, `white`.

## GET /api/v1/entity-events

Returns recent events for one entity.

Query parameters:

- `store_id` (required)
- `component` (required)
- `hours` (optional, default `24`, min `1`, max `168`)

Response behavior:

- Returns all event types (`problem`, `ok`, `disable`, `enable`) for the entity.
- Ordered newest first.
- Events only; acknowledgement activity is not included.

## Hierarchy status APIs

### GET /api/v1/status/stores

Returns store-level status hierarchy rows.

Response item fields:

- `store_id`
- `status_color` (highest-priority component status in the store)
- `component_count`
- `active_incident_count`

Severity precedence used for aggregation:

1. `red` (critical)
2. `yellow` (warning)
3. `purple` (stale)
4. `green` (ok)
5. `white` (disabled)

### GET /api/v1/status/stores/{store_id}/components

Returns component-level status rows for one store.

Response item fields:

- `store_id`
- `component`
- `status_color`
- `active_incident_count`
- `last_message`
- `last_event_id`
- `last_changed_at`
- `stale_interval_seconds`
- `disabled`

## Acknowledgements API

### GET /api/v1/acks

Returns all active acknowledgements.

### POST /api/v1/acks

Requires `X-Monitor-Key` header.

Payload:

```json
{
  "event_id": "evt-20260320-001",
  "ack_message": "Investigating",
  "ack_by": "operator-console",
  "expires_at": "2026-03-20T17:00:00Z"
}
```

`expires_at` is required and must be in the future.

### DELETE /api/v1/acks/{event_id}

Requires `X-Monitor-Key` header.

Expires an acknowledgement immediately.

## WebSocket /ws/updates

Pushes payloads with:
- `kind`: `event_update`
- `sequence`: monotonic integer
- `event`: normalized event payload
- `status`: latest entity status snapshot
- `deduplicated`: whether event was deduplicated on ingest

Additional kinds:
- `ack_update` with `ack` payload
- `ack_expired` with `event_id`
- `status_timeout` with `status` payload
