from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Acknowledgement, BroadcastEvent, EntityStatus, IncidentEvent, RetiredComponent, RetiredStore, RuntimeConfig, StreamCursor
from .schemas import (
    AckIn,
    AckOut,
    BootstrapOut,
    ComponentStatusOut,
    EntityStatusOut,
    EventIn,
    IncidentEventOut,
    MaintenanceListOut,
    RetiredComponentOut,
    RetiredStoreOut,
    RetireComponentIn,
    RetireStoreIn,
    RuntimeConfigOut,
    RuntimeConfigUpdateIn,
    StoreStatusOut,
    parse_stale_interval_seconds,
)


logger = logging.getLogger(__name__)
_LOG_FIELD_RE = re.compile(r"(?P<key>[a-z_]+)=(?P<value>[^\s]+)")
from .status_projection import should_change_state, should_mark_active, status_from_event, updated_count


def _color_rank(color: str) -> int:
    # Higher rank means higher alert priority for aggregation.
    return {
        "red": 5,
        "yellow": 4,
        "purple": 3,
        "green": 2,
        "white": 1,
    }.get(color, 0)


def _to_utc_naive(dt: datetime) -> datetime:
    """Strip timezone info after converting to UTC, for consistent SQLite storage."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _utc_now_naive() -> datetime:
    return datetime.utcnow()


def _canonical_event_type(event_type: str) -> str:
    # Keep ingest backward-compatible for legacy producers while standardizing output.
    if event_type == "recovery":
        return "ok"
    return event_type


def _log_files(log_dir: str, active_file_name: str) -> list[Path]:
    root = Path(log_dir)
    if not root.exists() or not root.is_dir():
        return []
    files = [path for path in root.iterdir() if path.is_file() and path.name.startswith(active_file_name)]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def list_log_files(log_dir: str, active_file_name: str) -> list[dict]:
    active_path = Path(log_dir) / active_file_name
    output: list[dict] = []
    for path in _log_files(log_dir, active_file_name):
        stat = path.stat()
        output.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime),
                "active": path.resolve() == active_path.resolve() if active_path.exists() else path.name == active_file_name,
            }
        )
    return output


def _parse_log_line(line: str) -> dict:
    raw = line.rstrip("\n")
    fields = {match.group("key"): match.group("value") for match in _LOG_FIELD_RE.finditer(raw)}
    timestamp = None
    ts_prefix = raw.split(" level=", 1)[0].strip()
    if ts_prefix:
        for pattern in (
            "%Y-%m-%d %H:%M:%S,%f",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ):
            try:
                timestamp = datetime.strptime(ts_prefix, pattern)
                break
            except ValueError:
                continue

    message = None
    marker = " msg="
    idx = raw.find(marker)
    if idx >= 0:
        message = raw[idx + len(marker) :]

    return {
        "timestamp": timestamp,
        "severity": (fields.get("level") or "").lower() or None,
        "message_type": fields.get("message_type"),
        "source": fields.get("source"),
        "state": fields.get("state"),
        "event_id": fields.get("event_id"),
        "client_ip": fields.get("client_ip"),
        "message": message,
        "raw": raw,
    }


def query_logs(
    log_dir: str,
    active_file_name: str,
    file_name: Optional[str],
    since: Optional[datetime],
    until: Optional[datetime],
    severity: Optional[str],
    message_type: Optional[str],
    source: Optional[str],
    state: Optional[str],
    event_id: Optional[str],
    client_ip: Optional[str],
    q: Optional[str],
    limit: int,
    offset: int,
) -> dict:
    selected_name = file_name or active_file_name
    root = Path(log_dir).resolve()
    selected_path = (root / selected_name).resolve()
    if root not in selected_path.parents and selected_path != root:
        return {"total": 0, "limit": limit, "offset": offset, "items": []}
    if not selected_path.exists() or not selected_path.is_file():
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    entries: list[dict] = []
    with selected_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parsed = _parse_log_line(line)

            if since and parsed["timestamp"] is None:
                continue
            if until and parsed["timestamp"] is None:
                continue
            if since and parsed["timestamp"] and parsed["timestamp"] < since:
                continue
            if until and parsed["timestamp"] and parsed["timestamp"] > until:
                continue
            if severity and (parsed["severity"] or "") != severity.lower():
                continue
            if message_type and (parsed["message_type"] or "") != message_type:
                continue
            if source and source.lower() not in (parsed["source"] or "").lower():
                continue
            if state and state.lower() not in (parsed["state"] or "").lower():
                continue
            if event_id and event_id.lower() not in (parsed["event_id"] or "").lower():
                continue
            if client_ip and client_ip.lower() not in (parsed["client_ip"] or "").lower():
                continue
            if q and q.lower() not in parsed["raw"].lower():
                continue

            entries.append(parsed)

    entries.reverse()
    total = len(entries)
    sliced = entries[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": sliced,
    }


def query_log_filter_values(log_dir: str, active_file_name: str, values_limit: int) -> dict:
    root = Path(log_dir).resolve()
    if not root.exists() or not root.is_dir():
        return {"message_types": [], "sources": [], "states": []}

    message_types: set[str] = set()
    sources: set[str] = set()
    states: set[str] = set()

    for selected_path in _log_files(log_dir, active_file_name):
        resolved_path = selected_path.resolve()
        if root not in resolved_path.parents and resolved_path != root:
            continue
        if not resolved_path.exists() or not resolved_path.is_file():
            continue

        with resolved_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parsed = _parse_log_line(line)

                message_type = (parsed.get("message_type") or "").strip()
                source = (parsed.get("source") or "").strip()
                state = (parsed.get("state") or "").strip()

                if message_type and message_type != "-":
                    message_types.add(message_type)
                if source and source != "-":
                    sources.add(source)
                if state and state != "-":
                    states.add(state)

                # Stop scanning as soon as all sets reached requested limits.
                if (
                    len(message_types) >= values_limit
                    and len(sources) >= values_limit
                    and len(states) >= values_limit
                ):
                    break

        if (
            len(message_types) >= values_limit
            and len(sources) >= values_limit
            and len(states) >= values_limit
        ):
            break

    return {
        "message_types": sorted(message_types)[:values_limit],
        "sources": sorted(sources)[:values_limit],
        "states": sorted(states)[:values_limit],
    }


def _cursor(db: Session) -> StreamCursor:
    cursor = db.scalar(select(StreamCursor).where(StreamCursor.id == 1))
    if cursor is None:
        cursor = StreamCursor(id=1, latest_sequence=0)
        db.add(cursor)
        db.flush()
    return cursor


def _runtime_config(db: Session) -> RuntimeConfig:
    row = db.scalar(select(RuntimeConfig).where(RuntimeConfig.id == 1))
    if row is None:
        row = RuntimeConfig(
            id=1,
            sweeper_interval_seconds=60,
            entity_history_default_limit=1000,
            entity_history_limit_options_json="[250,500,1000,2000]",
            log_max_mb=50,
            log_backup_count=20,
        )
        db.add(row)
        db.flush()
    return row


def get_runtime_config(db: Session) -> RuntimeConfigOut:
    row = _runtime_config(db)
    try:
        options = json.loads(row.entity_history_limit_options_json or "[]")
    except Exception:
        options = [250, 500, 1000, 2000]

    try:
        return RuntimeConfigOut(
            sweeper_interval_seconds=row.sweeper_interval_seconds,
            entity_history_default_limit=row.entity_history_default_limit,
            entity_history_limit_options=options,
            log_max_mb=row.log_max_mb,
            log_backup_count=row.log_backup_count,
        )
    except Exception:
        row.sweeper_interval_seconds = 60
        row.entity_history_default_limit = 1000
        row.entity_history_limit_options_json = "[250,500,1000,2000]"
        row.log_max_mb = 50
        row.log_backup_count = 20
        db.commit()
        return RuntimeConfigOut(
            sweeper_interval_seconds=60,
            entity_history_default_limit=1000,
            entity_history_limit_options=[250, 500, 1000, 2000],
            log_max_mb=50,
            log_backup_count=20,
        )


def update_runtime_config(db: Session, payload: RuntimeConfigUpdateIn) -> RuntimeConfigOut:
    row = _runtime_config(db)
    row.sweeper_interval_seconds = payload.sweeper_interval_seconds
    row.entity_history_default_limit = payload.entity_history_default_limit
    row.entity_history_limit_options_json = json.dumps(payload.entity_history_limit_options)
    row.log_max_mb = payload.log_max_mb
    row.log_backup_count = payload.log_backup_count
    db.commit()
    logger.info(
        "Runtime config updated",
        extra={
            "message_type": "runtime_config_update",
            "source": "config",
            "state": "applied",
        },
    )
    return RuntimeConfigOut(
        sweeper_interval_seconds=row.sweeper_interval_seconds,
        entity_history_default_limit=row.entity_history_default_limit,
        entity_history_limit_options=payload.entity_history_limit_options,
        log_max_mb=row.log_max_mb,
        log_backup_count=row.log_backup_count,
    )


def _entity_status(db: Session, store_id: str, component: str) -> EntityStatus:
    row = db.scalar(
        select(EntityStatus).where(
            EntityStatus.store_id == store_id,
            EntityStatus.component == component,
        )
    )
    if row is None:
        row = EntityStatus(
            store_id=store_id,
            component=component,
            status_color="green",
            active_incident_count=0,
            last_message="",
            last_event_id="",
            last_changed_at=datetime.utcnow(),
            stale_interval_seconds=None,
            last_checkin_at=datetime.utcnow(),
            disabled_at=None,
        )
        db.add(row)
        db.flush()
    return row


def _close_recoveries(db: Session, event: EventIn) -> int:
    base_query = select(IncidentEvent).where(
        IncidentEvent.store_id == event.store_id,
        IncidentEvent.component == event.component,
        IncidentEvent.active.is_(True),
    )

    if event.dedup_key:
        base_query = base_query.where(IncidentEvent.dedup_key == event.dedup_key)

    rows = db.scalars(base_query).all()
    for row in rows:
        row.active = False
    return len(rows)


def _close_all_active_for_entity(db: Session, store_id: str, component: str) -> int:
    rows = db.scalars(
        select(IncidentEvent).where(
            IncidentEvent.store_id == store_id,
            IncidentEvent.component == component,
            IncidentEvent.active.is_(True),
        )
    ).all()
    for row in rows:
        row.active = False
    return len(rows)


def _retired_store_ids(db: Session) -> set[str]:
    return set(db.scalars(select(RetiredStore.store_id)).all())


def _retired_component_keys(db: Session) -> set[tuple[str, str]]:
    rows = db.execute(select(RetiredComponent.store_id, RetiredComponent.component)).all()
    return {(r.store_id, r.component) for r in rows}


def _clear_retirement(db: Session, store_id: str, component: str) -> None:
    """Remove any retirement records for this entity so it reappears after a new event."""
    db.execute(
        select(RetiredStore).where(RetiredStore.store_id == store_id)
    )
    store_row = db.scalar(select(RetiredStore).where(RetiredStore.store_id == store_id))
    if store_row is not None:
        db.delete(store_row)

    comp_row = db.scalar(
        select(RetiredComponent).where(
            RetiredComponent.store_id == store_id,
            RetiredComponent.component == component,
        )
    )
    if comp_row is not None:
        db.delete(comp_row)


def set_entity_disabled(db: Session, store_id: str, component: str, disabled: bool) -> dict:
    """Set or clear the disabled state for a specific store/component in EntityStatus."""
    status = _entity_status(db, store_id, component)
    now = _utc_now_naive()
    if disabled:
        status.disabled_at = now
        status.status_color = "white"
        status.stale_interval_seconds = None
        _close_all_active_for_entity(db, status.store_id, status.component)
        status.active_incident_count = 0
        status.last_changed_at = now
    else:
        status.disabled_at = None
        status.status_color = "green"
        status.last_changed_at = now
    db.commit()
    return {
        "store_id": status.store_id,
        "component": status.component,
        "status_color": status.status_color,
        "active_incident_count": status.active_incident_count,
        "last_message": status.last_message,
        "last_event_id": status.last_event_id,
        "last_changed_at": status.last_changed_at,
        "stale_interval_seconds": status.stale_interval_seconds,
        "disabled": status.disabled_at is not None,
    }


def retire_store(db: Session, store_id: str) -> RetiredStoreOut:
    row = db.scalar(select(RetiredStore).where(RetiredStore.store_id == store_id))
    if row is None:
        row = RetiredStore(store_id=store_id, retired_at=_utc_now_naive())
        db.add(row)
        db.commit()
        db.refresh(row)
    return RetiredStoreOut(store_id=row.store_id, retired_at=row.retired_at)


def retire_component(db: Session, store_id: str, component: str) -> RetiredComponentOut:
    row = db.scalar(
        select(RetiredComponent).where(
            RetiredComponent.store_id == store_id,
            RetiredComponent.component == component,
        )
    )
    if row is None:
        row = RetiredComponent(store_id=store_id, component=component, retired_at=_utc_now_naive())
        db.add(row)
        db.commit()
        db.refresh(row)
    return RetiredComponentOut(store_id=row.store_id, component=row.component, retired_at=row.retired_at)


def retire_component_globally(db: Session, component: str) -> list[RetiredComponentOut]:
    """Retire a component across every store that currently has it in EntityStatus."""
    store_ids = sorted(db.scalars(
        select(EntityStatus.store_id)
        .where(EntityStatus.component == component)
        .distinct()
    ).all())

    now = _utc_now_naive()
    for store_id in store_ids:
        existing = db.scalar(
            select(RetiredComponent).where(
                RetiredComponent.store_id == store_id,
                RetiredComponent.component == component,
            )
        )
        if existing is None:
            db.add(RetiredComponent(store_id=store_id, component=component, retired_at=now))

    db.commit()

    rows = db.scalars(
        select(RetiredComponent)
        .where(RetiredComponent.component == component)
        .order_by(RetiredComponent.store_id)
    ).all()
    return [RetiredComponentOut(store_id=r.store_id, component=r.component, retired_at=r.retired_at) for r in rows]


def restore_store(db: Session, store_id: str) -> bool:
    row = db.scalar(select(RetiredStore).where(RetiredStore.store_id == store_id))
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def restore_component(db: Session, store_id: str, component: str) -> bool:
    row = db.scalar(
        select(RetiredComponent).where(
            RetiredComponent.store_id == store_id,
            RetiredComponent.component == component,
        )
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def get_maintenance_list(db: Session) -> MaintenanceListOut:
    stores = db.scalars(select(RetiredStore).order_by(RetiredStore.store_id)).all()
    components = db.scalars(
        select(RetiredComponent).order_by(RetiredComponent.store_id, RetiredComponent.component)
    ).all()
    return MaintenanceListOut(
        retired_stores=[RetiredStoreOut(store_id=r.store_id, retired_at=r.retired_at) for r in stores],
        retired_components=[
            RetiredComponentOut(store_id=r.store_id, component=r.component, retired_at=r.retired_at)
            for r in components
        ],
    )


def ingest_event(db: Session, event: EventIn) -> tuple[bool, bool, Optional[int], dict]:
    canonical_event_type = _canonical_event_type(event.event_type)
    logger.info(
        "Ingest event received",
        extra={
            "message_type": "ingest_event",
            "source": event.source,
            "event_id": event.event_id,
        },
    )

    existing = db.scalar(select(IncidentEvent).where(IncidentEvent.event_id == event.event_id))
    if existing is not None:
        logger.warning(
            "Event replay detected",
            extra={
                "message_type": "ingest_event",
                "source": event.source,
                "event_id": event.event_id,
                "state": "idempotent_replay",
            },
        )
        return True, True, None, {}

    # Auto-restore retirement when a new (non-duplicate) event is received.
    _clear_retirement(db, event.store_id, event.component)

    duplicate_problem = False
    if canonical_event_type == "problem":
        duplicate_problem = db.scalar(
            select(IncidentEvent).where(
                IncidentEvent.store_id == event.store_id,
                IncidentEvent.component == event.component,
                IncidentEvent.dedup_key == event.dedup_key,
                IncidentEvent.active.is_(True),
            )
        ) is not None

    closed_count = 0
    if canonical_event_type == "ok":
        closed_count = _close_recoveries(db, event)
    elif canonical_event_type == "disable":
        closed_count = _close_all_active_for_entity(db, event.store_id, event.component)

    happened_at_naive = _utc_now_naive()
    next_color = status_from_event(canonical_event_type, event.severity)

    incident = IncidentEvent(
        event_id=event.event_id,
        dedup_key=event.dedup_key,
        store_id=event.store_id,
        component=event.component,
        event_type=canonical_event_type,
        severity=event.severity,
        message=event.message,
        source=event.source,
        metadata_json=json.dumps(event.metadata),
        happened_at=happened_at_naive,
        expires_at=None,
        active=should_mark_active(canonical_event_type, next_color) and not duplicate_problem,
    )
    db.add(incident)

    status = _entity_status(db, event.store_id, event.component)
    green_reset = (
        status.disabled_at is None
        and next_color == "green"
        and status.status_color in {"red", "yellow", "purple"}
    )

    status.last_checkin_at = happened_at_naive
    if event.stale_interval is not None:
        status.stale_interval_seconds = parse_stale_interval_seconds(event.stale_interval)
    else:
        status.stale_interval_seconds = None

    if canonical_event_type == "disable":
        status.disabled_at = happened_at_naive
    elif canonical_event_type == "enable":
        status.disabled_at = None

    # Disabled components never participate in stale timeout logic.
    if status.disabled_at is not None:
        status.stale_interval_seconds = None

    if status.disabled_at is not None and canonical_event_type not in {"enable", "disable"}:
        incident.active = False
        next_color = "white"
        closed_count = max(closed_count, status.active_incident_count)

    if green_reset:
        incident.active = False
        closed_count = max(closed_count, _close_all_active_for_entity(db, event.store_id, event.component))

    if green_reset:
        status.active_incident_count = 0
    else:
        status.active_incident_count = updated_count(
            status.active_incident_count,
            canonical_event_type,
            closed_for_entity=closed_count,
            deduplicated=duplicate_problem,
            increment_active=incident.active,
        )
    status.last_message = event.message
    status.last_event_id = event.event_id
    if should_change_state(status.status_color, next_color, happened_at_naive, status.last_changed_at):
        status.status_color = next_color
        status.last_changed_at = happened_at_naive

    cursor = _cursor(db)
    cursor.latest_sequence += 1

    payload = {
        "kind": "event_update",
        "sequence": cursor.latest_sequence,
        "event": {
            "event_id": event.event_id,
            "dedup_key": event.dedup_key,
            "store_id": event.store_id,
            "component": event.component,
            "event_type": canonical_event_type,
            "severity": event.severity,
            "message": event.message,
            "source": event.source,
            "happened_at": happened_at_naive.isoformat(),
            "expires_at": incident.expires_at.isoformat() if incident.expires_at else None,
            "active": incident.active,
            "metadata": json.loads(incident.metadata_json or "{}"),
        },
        "status": {
            "store_id": status.store_id,
            "component": status.component,
            "status_color": status.status_color,
            "active_incident_count": status.active_incident_count,
            "last_message": status.last_message,
            "last_event_id": status.last_event_id,
            "last_changed_at": status.last_changed_at.isoformat(),
            "stale_interval_seconds": status.stale_interval_seconds,
            "disabled": status.disabled_at is not None,
        },
        "deduplicated": duplicate_problem,
    }

    db.add(
        BroadcastEvent(
            sequence=cursor.latest_sequence,
            event_id=event.event_id,
            payload_json=json.dumps(payload),
        )
    )

    db.commit()
    logger.info(
        "Event ingested",
        extra={
            "message_type": canonical_event_type,
            "source": event.source,
            "state": status.status_color,
            "event_id": event.event_id,
        },
    )
    return True, duplicate_problem, cursor.latest_sequence, payload


def bootstrap(db: Session, recent_limit: int) -> BootstrapOut:
    cursor = _cursor(db)

    retired_stores = _retired_store_ids(db)
    retired_components = _retired_component_keys(db)

    statuses = db.scalars(
        select(EntityStatus).order_by(EntityStatus.status_color.desc(), EntityStatus.store_id.asc(), EntityStatus.component.asc())
    ).all()

    recent = db.scalars(
        select(IncidentEvent).order_by(IncidentEvent.happened_at.desc()).limit(recent_limit)
    ).all()

    active_acks = get_active_acks(db)
    runtime_config = get_runtime_config(db)

    return BootstrapOut(
        latest_sequence=cursor.latest_sequence,
        statuses=[
            EntityStatusOut(
                store_id=s.store_id,
                component=s.component,
                status_color=s.status_color,
                active_incident_count=s.active_incident_count,
                last_message=s.last_message,
                last_event_id=s.last_event_id,
                last_changed_at=s.last_changed_at,
                stale_interval_seconds=s.stale_interval_seconds,
                disabled=s.disabled_at is not None,
            )
            for s in statuses
            if s.store_id not in retired_stores and (s.store_id, s.component) not in retired_components
        ],
        recent_events=[
            IncidentEventOut(
                event_id=e.event_id,
                dedup_key=e.dedup_key,
                store_id=e.store_id,
                component=e.component,
                event_type=_canonical_event_type(e.event_type),
                severity=e.severity,
                message=e.message,
                source=e.source,
                happened_at=e.happened_at,
                active=e.active,
                metadata=json.loads(e.metadata_json or "{}"),
            )
            for e in recent
        ],
        active_acks=active_acks,
        config=runtime_config,
    )


def get_summary_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(EntityStatus.status_color, func.count(EntityStatus.id)).group_by(EntityStatus.status_color)).all()
    counts = {"green": 0, "yellow": 0, "red": 0, "purple": 0, "white": 0}
    for color, count in rows:
        if color in counts:
            counts[color] = count
    return counts


def get_active_incidents_for_entity(db: Session, store_id: str, component: str) -> list[IncidentEventOut]:
    rows = db.scalars(
        select(IncidentEvent)
        .where(
            IncidentEvent.store_id == store_id,
            IncidentEvent.component == component,
            IncidentEvent.active.is_(True),
        )
        .order_by(IncidentEvent.happened_at.desc())
    ).all()
    return [
        IncidentEventOut(
            event_id=row.event_id,
            dedup_key=row.dedup_key,
            store_id=row.store_id,
            component=row.component,
            event_type=_canonical_event_type(row.event_type),
            severity=row.severity,
            message=row.message,
            source=row.source,
            happened_at=row.happened_at,
            active=row.active,
            metadata=json.loads(row.metadata_json or "{}"),
        )
        for row in rows
    ]


def get_recent_events_for_entity(
    db: Session,
    store_id: str,
    component: str,
    hours: int = 24,
    limit: int = 1000,
) -> list[IncidentEventOut]:
    safe_hours = min(max(hours, 1), 168)
    safe_limit = min(max(limit, 50), 2000)
    since = _utc_now_naive() - timedelta(hours=safe_hours)

    rows = db.scalars(
        select(IncidentEvent)
        .where(
            IncidentEvent.store_id == store_id,
            IncidentEvent.component == component,
            IncidentEvent.happened_at >= since,
        )
        .order_by(IncidentEvent.happened_at.desc())
        .limit(safe_limit)
    ).all()

    incident_out = [
        IncidentEventOut(
            event_id=row.event_id,
            dedup_key=row.dedup_key,
            store_id=row.store_id,
            component=row.component,
            event_type=_canonical_event_type(row.event_type),
            severity=row.severity,
            message=row.message,
            source=row.source,
            happened_at=row.happened_at,
            active=row.active,
            metadata=json.loads(row.metadata_json or "{}"),
        )
        for row in rows
    ]

    ack_rows = db.scalars(
        select(Acknowledgement)
        .where(
            Acknowledgement.store_id == store_id,
            Acknowledgement.component == component,
            (Acknowledgement.acknowledged_at >= since) | (Acknowledgement.expired_at >= since),
        )
    ).all()

    ack_out: list[IncidentEventOut] = []
    for row in ack_rows:
        ack_source = f"ack:{row.ack_by}" if row.ack_by else "ack:operator"

        if row.acknowledged_at is not None and row.acknowledged_at >= since:
            ack_out.append(
                IncidentEventOut(
                    event_id=f"ack-{row.event_id}-{row.acknowledged_at.isoformat()}",
                    dedup_key=row.event_id,
                    store_id=row.store_id,
                    component=row.component,
                    event_type="ack",
                    severity="info",
                    message=row.ack_message or "Acknowledged by operator",
                    source=ack_source,
                    happened_at=row.acknowledged_at,
                    active=True,
                    metadata={
                        "acknowledged_event_id": row.event_id,
                        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                    },
                )
            )

        if row.expired_at is not None and row.expired_at >= since:
            ack_out.append(
                IncidentEventOut(
                    event_id=f"ack-expired-{row.event_id}-{row.expired_at.isoformat()}",
                    dedup_key=row.event_id,
                    store_id=row.store_id,
                    component=row.component,
                    event_type="ack_expired",
                    severity="info",
                    message="Acknowledgement expired",
                    source=ack_source,
                    happened_at=row.expired_at,
                    active=False,
                    metadata={
                        "acknowledged_event_id": row.event_id,
                        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                    },
                )
            )

    merged = incident_out + ack_out
    merged.sort(key=lambda row: (row.happened_at, row.event_id), reverse=True)
    return merged[:safe_limit]


def get_store_statuses(db: Session) -> list[StoreStatusOut]:
    retired_stores = _retired_store_ids(db)
    retired_components = _retired_component_keys(db)

    rows = db.scalars(select(EntityStatus)).all()
    grouped: dict[str, list[EntityStatus]] = defaultdict(list)
    for row in rows:
        if row.store_id in retired_stores:
            continue
        if (row.store_id, row.component) in retired_components:
            continue
        grouped[row.store_id].append(row)

    stores: list[StoreStatusOut] = []
    for store_id in sorted(grouped.keys()):
        entries = grouped[store_id]
        highest = max(entries, key=lambda entry: _color_rank(entry.status_color))
        stores.append(
            StoreStatusOut(
                store_id=store_id,
                status_color=highest.status_color,
                component_count=len(entries),
                active_incident_count=sum(entry.active_incident_count for entry in entries),
            )
        )
    return stores


def get_component_statuses_for_store(db: Session, store_id: str) -> list[ComponentStatusOut]:
    retired_stores = _retired_store_ids(db)
    retired_components = _retired_component_keys(db)

    rows = db.scalars(
        select(EntityStatus)
        .where(EntityStatus.store_id == store_id)
        .order_by(EntityStatus.component.asc())
    ).all()

    return [
        ComponentStatusOut(
            store_id=row.store_id,
            component=row.component,
            status_color=row.status_color,
            active_incident_count=row.active_incident_count,
            last_message=row.last_message,
            last_event_id=row.last_event_id,
            last_changed_at=row.last_changed_at,
            stale_interval_seconds=row.stale_interval_seconds,
            disabled=row.disabled_at is not None,
        )
        for row in rows
        if row.store_id not in retired_stores and (row.store_id, row.component) not in retired_components
    ]


def create_ack(db: Session, ack: AckIn) -> tuple[Optional[AckOut], dict]:
    incident = db.scalar(select(IncidentEvent).where(IncidentEvent.event_id == ack.event_id))
    if incident is None:
        logger.warning(
            "Ack requested for missing event",
            extra={
                "message_type": "ack_update",
                "event_id": ack.event_id,
                "state": "missing_event",
            },
        )
        return None, {}

    if incident.event_type != "problem":
        logger.warning(
            "Ack requested for non-ackable event",
            extra={
                "message_type": "ack_update",
                "event_id": ack.event_id,
                "state": "not_ackable",
            },
        )
        return None, {"error": "not_ackable"}

    row = db.scalar(select(Acknowledgement).where(Acknowledgement.event_id == ack.event_id))
    if row is None:
        row = Acknowledgement(
            event_id=ack.event_id,
            store_id=incident.store_id,
            component=incident.component,
            ack_message=ack.ack_message,
            ack_by=ack.ack_by,
            expires_at=_to_utc_naive(ack.expires_at),
            acknowledged_at=_utc_now_naive(),
            active=True,
        )
        db.add(row)
    else:
        row.ack_message = ack.ack_message
        row.ack_by = ack.ack_by
        row.expires_at = _to_utc_naive(ack.expires_at)
        row.acknowledged_at = _utc_now_naive()
        row.expired_at = None
        row.active = True

    db.commit()
    logger.info(
        "Acknowledgement upserted",
        extra={
            "message_type": "ack_update",
            "source": "ack",
            "event_id": ack.event_id,
            "state": "active",
        },
    )

    ack_out = AckOut(
        event_id=row.event_id,
        store_id=row.store_id,
        component=row.component,
        ack_message=row.ack_message,
        expires_at=row.expires_at,
        acknowledged_at=row.acknowledged_at,
        ack_by=row.ack_by,
    )
    payload = {
        "kind": "ack_update",
        "ack": ack_out.model_dump(mode="json"),
    }
    return ack_out, payload


def get_active_acks(db: Session) -> list[AckOut]:
    rows = db.scalars(
        select(Acknowledgement)
        .where(Acknowledgement.active.is_(True))
        .order_by(Acknowledgement.expires_at.asc())
    ).all()
    return [
        AckOut(
            event_id=row.event_id,
            store_id=row.store_id,
            component=row.component,
            ack_message=row.ack_message,
            expires_at=row.expires_at,
            acknowledged_at=row.acknowledged_at,
            ack_by=row.ack_by,
        )
        for row in rows
    ]


def expire_ack(db: Session, event_id: str) -> Optional[dict]:
    row = db.scalar(
        select(Acknowledgement).where(
            Acknowledgement.event_id == event_id,
            Acknowledgement.active.is_(True),
        )
    )
    if row is None:
        logger.warning(
            "Ack expiry skipped for missing active ack",
            extra={
                "message_type": "ack_expired",
                "event_id": event_id,
                "state": "not_found",
            },
        )
        return None
    row.active = False
    row.expired_at = _utc_now_naive()
    db.commit()
    logger.info(
        "Acknowledgement expired",
        extra={
            "message_type": "ack_expired",
            "event_id": event_id,
            "state": "expired",
        },
    )
    return {"kind": "ack_expired", "event_id": event_id}


def sweep_expired_acks(db: Session) -> list[dict]:
    now = _utc_now_naive()
    rows = db.scalars(
        select(Acknowledgement).where(
            Acknowledgement.active.is_(True),
            Acknowledgement.expires_at <= now,
        )
    ).all()
    payloads = []
    for row in rows:
        row.active = False
        row.expired_at = now
        payloads.append({"kind": "ack_expired", "event_id": row.event_id})

    if payloads:
        db.commit()
        logger.info(
            "Ack sweep expired active acknowledgements",
            extra={
                "message_type": "ack_sweep",
                "source": "sweeper",
                "state": "expired",
            },
        )
    return payloads


def sweep_timeout_statuses(db: Session) -> list[dict]:
    now = _utc_now_naive()
    rows = db.scalars(
        select(EntityStatus).where(
            EntityStatus.disabled_at.is_(None),
            EntityStatus.stale_interval_seconds.is_not(None),
            EntityStatus.last_checkin_at.is_not(None),
        )
    ).all()

    payloads: list[dict] = []
    for row in rows:
        assert row.last_checkin_at is not None
        assert row.stale_interval_seconds is not None
        elapsed = (now - row.last_checkin_at).total_seconds()
        if elapsed <= row.stale_interval_seconds:
            continue
        if row.status_color == "purple":
            continue

        row.status_color = "purple"
        row.last_changed_at = now
        row.last_message = "Heartbeat timeout: expected green check-in was missed"
        payloads.append(
            {
                "kind": "status_timeout",
                "status": {
                    "store_id": row.store_id,
                    "component": row.component,
                    "status_color": row.status_color,
                    "active_incident_count": row.active_incident_count,
                    "last_message": row.last_message,
                    "last_event_id": row.last_event_id,
                    "last_changed_at": row.last_changed_at.isoformat(),
                    "stale_interval_seconds": row.stale_interval_seconds,
                    "disabled": False,
                },
            }
        )

    if payloads:
        db.commit()
        logger.info(
            "Status timeout sweep marked stale entities",
            extra={
                "message_type": "status_timeout",
                "source": "sweeper",
                "state": "purple",
            },
        )
    return payloads
