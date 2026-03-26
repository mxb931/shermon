## Plan: Unified Tabs, Test Sender, and Five-Level Monitoring

Deliver a cohesive operator UI with top navigation tabs (Alerts, Acknowledgements, Test Sender, Help) while implementing five-level monitor behavior (red/yellow/green/purple/white), heartbeat timeout rules, event-level expiration support, and user-facing in-app documentation.

**Steps**
1. Phase 1 — API and domain foundation
2. Expand status typing to five values (`red`, `yellow`, `green`, `purple`, `white`) in outbound schemas and docs.
3. Extend event types to include lifecycle control (`disable`, `enable`) while keeping `problem|recovery` compatibility.
4. Add optional heartbeat interval field on ingest payload (`expected_green_interval_seconds`) to support purple timeout detection.
5. Add event-ingest expiration field on POST events (`expires_at` datetime, optional in contract, validated when present) and define behavior for expired events.
6. Implement acknowledgement API contract (create/list/expire): include message and required absolute expiry datetime (`expires_at`).
7. Keep existing ingest payload fields backward compatible; old senders without new fields continue to work unchanged.

8. Phase 2 — Persistence and projection logic
9. Extend entity status persistence with heartbeat/disable tracking (`expected_green_interval_seconds`, `last_checkin_at`, `disabled_at`).
10. Add event expiration persistence handling so expired events are deterministically treated (documented behavior and tests).
11. Add acknowledgement persistence model for active acknowledgements and expiry state.
12. Projection precedence:
13. `disable` event -> white, suppress timeout checks.
14. `enable` event -> green, resume timeout checks.
15. `recovery` event -> green.
16. timeout evaluator -> purple only when interval is set and check-in is overdue.
17. legacy severity mapping for problem events remains critical->red, warning->yellow, info->green.
18. Any incoming event refreshes heartbeat last check-in time.

19. Phase 3 — Background evaluators and realtime fanout
20. Add periodic timeout sweeper (recommended 60s) to set overdue entities to purple.
21. Add periodic ack-expiry sweeper to expire stale acknowledgements when `expires_at <= now`.
22. Broadcast websocket updates for status changes and acknowledgement state changes.
23. Ensure timeout evaluator skips disabled (white) entities and entities without interval.

24. Phase 4 — Dashboard top menu and tab architecture
25. Refactor dashboard shell to include a top tab/menu bar under page title.
26. Add tabs: Alerts, Acknowledgements, Test Sender, Help.
27. Keep each tab as a dedicated panel/page section with clear active state and keyboard-accessible tab switching.
28. Preserve mobile layout behavior so tabs wrap/scroll without breaking existing cards and lists.

29. Phase 5 — Alerts and Acknowledgements UX
30. Add acknowledge modal from Alerts list click action.
31. Capture acknowledgement message and required expiry datetime (date/time picker).
32. Move acknowledged incidents to Acknowledgements tab and show remaining time until expiry.
33. On expiry, automatically return incidents to Alerts tab.

34. Phase 6 — Dedicated Test Sender page (two modes)
35. Add a separate Test Sender page/tab for sending test data to APIs.
36. Provide two modes: Event mode (POST /api/v1/events) and Acknowledgement mode (ack endpoints).
37. Event mode fields:
38. include all required event fields plus optional `expected_green_interval_seconds` and optional `expires_at` via date/time picker.
39. constrain enum fields (`event_type`, `severity`) to valid values; constrain non-message values with selectors/generators where practical.
40. Acknowledgement mode fields:
41. incident/event selector, required `expires_at` via date/time picker, plus message.
42. Restrict freeform typing to `message` only.
43. Metadata handling uses predefined templates only (no freeform JSON editor).
44. Validate client-side before submit and show normalized payload preview plus API response panel.
45. Include API key input for authenticated test calls and clear error feedback for auth/validation failures.
46. Date/time picker UX: display in user local time, submit UTC ISO timestamp.

47. Phase 7 — Help page in top menu
48. Add a dedicated Help tab/page in the same menu bar as Alerts/Acknowledgements/Test Sender.
49. Structure Help content for operators (not developers):
50. Quick Start (how to read dashboard, basic daily workflow).
51. Field Glossary (store, component, category, event type, severity, status color, dedup key, heartbeat interval, disable/enable, event expiration).
52. Alert Meaning Guide for all five levels.
53. Acknowledgements guide: how to acknowledge, why expiry is required, and how items return to alerts.
54. Troubleshooting section: connection badge meanings, API key issues, common payload mistakes.
55. Embed links to detailed API docs for deeper technical reference.

56. Phase 8 — Documentation synchronization
57. Update API reference docs for new fields/endpoints/status values, including event-level `expires_at` and required ack `expires_at`.
58. Add end-user documentation snippets aligned with Help tab wording.
59. Update README section describing tabs and five-level status behavior.
60. Keep developer guide examples synchronized with new event and acknowledgement expiration datetime usage.

61. Phase 9 — Verification and acceptance
62. Backend tests:
63. five-level summary counts always present.
64. purple timeout triggers only when interval is configured.
65. white disable suppresses timeout; enable resumes timeout eligibility.
66. event-level `expires_at` validation and behavior for expired events.
67. acknowledgement create/list/expire with required expiry and websocket propagation.
68. Frontend tests/manual checks:
69. tab navigation works on desktop and mobile.
70. test sender enforces only-message-freeform rule.
71. test sender uses metadata templates only.
72. date/time pickers are used for both event `expires_at` and ack `expires_at`.
73. date/time values display local and submit UTC ISO.
74. help content renders correctly and matches live behavior.
75. multi-tab/browser realtime consistency for alert/ack transitions.

**Relevant files**
- `backend/app/schemas.py` — status/event enums, heartbeat field, event `expires_at`, ack contracts.
- `backend/app/models.py` — heartbeat/disable persistence, event expiry representation, acknowledgement model.
- `backend/app/status_projection.py` — five-level transition precedence.
- `backend/app/repository.py` — ingest updates, timeout sweep logic, event-expiry handling, ack lifecycle operations, five-key summary shape.
- `backend/app/main.py` — routes for acknowledgements, startup background sweepers, realtime integration.
- `backend/tests/smoke_test.py` — expanded coverage for timeout, disable/enable, event expiry, acknowledgements, summary.
- `frontend/index.html` — top menu tabs and panel containers (Alerts/Acknowledgements/Test Sender/Help).
- `frontend/main.js` — tab router/state, acknowledgement flows, two-mode test sender logic, local-time picker to UTC conversion.
- `frontend/styles.css` — tab/menu styles, purple/white styles, test form styles, help content styles.
- `docs/api/monitoring-events-v1.md` — updated API contract details.
- `docs/api/developer-usage.md` — updated field definitions and examples.
- `README.md` — user-facing summary of tab navigation and statuses.

**Verification**
1. Confirm `/api/v1/summary` returns all five status keys including zeros.
2. Ingest with interval, miss check-in, verify purple transition and websocket update.
3. Disable entity, verify white state and no purple transition while disabled.
4. Enable entity, verify return to green and timeout eligibility resumes.
5. Ingest event with `expires_at` in the past, verify documented expired-event behavior.
6. Acknowledge incident with required expiry datetime, verify move to Acknowledgements tab and automatic return on expiry.
7. Test Sender: only `message` allows arbitrary free text; all other fields constrained to valid values/selectors/templates.
8. Test Sender: both date/time pickers display local time and submit UTC ISO payload values.
9. Help tab appears in same top menu bar and includes field glossary plus five-level alert meaning guide.

**Decisions**
- Top menu includes four tabs: Alerts, Acknowledgements, Test Sender, Help.
- Help content is end-user oriented and links to deeper API docs.
- Purple timeout behavior remains interval-driven and optional (no interval means no purple).
- White/Clear is controlled via explicit disable/enable lifecycle events.
- Event ingest includes datetime `expires_at` support.
- Acknowledgement expiry datetime is required.
- Test Sender supports two modes: Event and Acknowledgement.
- Only `message` is freeform; all other fields are constrained controls.
- Metadata in Test Sender is template-based only.
- Date/time controls display local time and submit UTC ISO values.
- Event requests with past `expires_at` are rejected with 422 validation error.

**Further Considerations**
1. If strict non-freeform IDs are required, use generated IDs and selectors rather than text inputs.
2. For production scale, move timeout and ack-expiry sweepers from in-process tasks to a shared scheduler/worker.
