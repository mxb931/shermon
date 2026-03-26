# Monitoring Events API v1

This API has been migrated to a standard OpenAPI 3.1 document.

Primary source of truth:

- `docs/api/monitoring-events-v1.openapi.yaml`

What the OpenAPI migration now covers:

- Every HTTP endpoint implemented in the backend, including `/api/v1/active-alerts` query parameters (`store_id`, `component`) and all runtime config, logs, hierarchy, and ack routes.
- Request/response schemas with required fields, enum values, min/max constraints, and nullable fields.
- Header security scheme (`X-Monitor-Key`) applied only to endpoints that require auth.
- Validation and error response shapes (`401`, `404`, `422`) for endpoint behaviors present in the implementation.
- Query defaults and limits for logs and entity event history.
- Health endpoint (`/health`) and WebSocket channel notes (`/ws/updates`).
