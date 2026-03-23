# SherMon Technical Specification

## Purpose

SherMon is a lightweight monitoring platform for Xstore operations. It ingests incident events, projects entity health, streams real-time updates to a browser dashboard, and supports acknowledgements with expiry.

## High-Level Architecture

- Backend API service: FastAPI app exposing REST and WebSocket endpoints.
- Persistence layer: SQLite database accessed through SQLAlchemy ORM.
- Frontend dashboard: static multi-page HTML/CSS/JavaScript application.
- Deployment shell: Docker Compose orchestration for API and static UI.
- Integration helper: Java client class for posting events from Xstore-adjacent systems.

## Technology Stack And Rationale

| Technology | Where Used | Why It Was Chosen |
|---|---|---|
| Python | Backend service (`backend/app`) | Fast development cycle, readable service logic, and strong ecosystem support for API/data tooling. |
| FastAPI (`0.115.12`) | HTTP and WebSocket API | High productivity for typed APIs, built-in OpenAPI docs, and async support for realtime flows. |
| Uvicorn (`0.34.0`) | ASGI server runtime | Lightweight, production-proven ASGI server that pairs directly with FastAPI. |
| Pydantic (`2.10.6`) | Request/response schemas and validation | Declarative input validation and schema-driven contracts reduce invalid payload risk. |
| SQLAlchemy (`2.0.39`) | Data access and ORM models | Clear domain modeling with portable SQL/query support and transaction control. |
| SQLite | Primary data store (MVP) | Zero-ops local persistence, easy setup for early-stage development, and fast iteration. |
| Raw SQL migration hooks | Schema compatibility in startup lifecycle | Enables incremental schema evolution for existing local DBs without external migration tooling in MVP. |
| WebSocket protocol | `/ws/updates` stream | Delivers low-latency push updates for incident/status/ack changes without polling overhead. |
| Vanilla JavaScript (ES modules) | Frontend logic (`frontend/*.js`) | No build step required; keeps the UI stack simple and easy to debug in early stages. |
| HTML5/CSS3 | Frontend UI (`frontend/*.html`, `frontend/styles.css`) | Straightforward static dashboard delivery and fast UI iteration. |
| Nginx (alpine image) | Static frontend hosting in Docker | Small, reliable static asset server with minimal configuration overhead. |
| Docker Compose | Local multi-service orchestration (`deploy/docker-compose.yml`) | One-command startup for API + UI, consistent environments across machines. |
| Java 11+ `HttpClient` | Xstore integration helper (`xstore-integration/java/MonitorClient.java`) | Uses standard JDK networking APIs to avoid external Java dependencies. |
| Shell + Python smoke tests | API validation (`backend/tests`) | Fast regression checks covering auth, ingest, projection, summary, and acknowledgement lifecycle. |

## Backend Technical Details

### Runtime and API

- FastAPI application entrypoint: `backend/app/main.py`.
- Core API styles:
  - REST endpoints for ingest, bootstrap, summary, and acknowledgement actions.
  - WebSocket endpoint for realtime update events.
- Authentication pattern:
  - Header-based shared key (`X-Monitor-Key`) checked server-side.

### Data and Domain Model

- ORM models include:
  - Incident events
  - Entity status projection
  - Stream cursor for sequencing
  - Broadcast events
  - Acknowledgements
- Repository pattern in `backend/app/repository.py` encapsulates ingest, projection updates, summary calculations, and acknowledgement lifecycle behavior.

### Realtime Behavior

- Event ingest and sweeper tasks emit broadcast payloads.
- Frontend clients subscribe to websocket updates and reconcile local UI state from push events.

## Frontend Technical Details

- Static multi-page navigation:
  - Alerts
  - Acknowledgements
  - Test Sender
  - Help
- Browser APIs used:
  - `fetch` for REST calls
  - `WebSocket` for realtime subscriptions
  - `dialog` element for acknowledgement modal workflows
- State management approach:
  - In-memory maps/arrays per page script (no external state library)
  - Deterministic newest-first incident ordering in alert stream rendering

## Deployment and Operations

- Compose services:
  - `api`: Python slim image running FastAPI via Uvicorn
  - `dashboard`: Nginx serving static frontend files
- Config surface:
  - Environment variables for API key, DB URL, and limits.
- Health and smoke verification:
  - `/health` endpoint
  - `backend/tests/run_smoke.sh` for reproducible end-to-end checks

## Design Tradeoffs

- Chosen for MVP speed:
  - SQLite and static frontend avoid operational overhead.
  - No frontend build pipeline reduces complexity.
- Tradeoff accepted:
  - Limited horizontal scaling and migration sophistication compared with a production-grade Postgres + managed migration framework setup.
- Planned growth path:
  - Move to PostgreSQL and stronger migration strategy as data volume and deployment complexity increase.
