from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import BroadcastEvent, EntityStatus, IncidentEvent, StreamCursor
from .schemas import BootstrapOut, EntityStatusOut, EventIn, IncidentEventOut
from .status_projection import should_change_state, should_mark_active, status_from_event, updated_count


def _to_utc_naive(dt: datetime) -> datetime:
    """Strip timezone info after converting to UTC, for consistent SQLite storage."""
    if dt.tzinfo is not None:
        dt = dt.utctimetuple()
        return datetime(*dt[:6])
    return dt


def _cursor(db: Session) -> StreamCursor:
    cursor = db.scalar(select(StreamCursor).where(StreamCursor.id == 1))
    if cursor is None:
        cursor = StreamCursor(id=1, latest_sequence=0)
        db.add(cursor)
        db.flush()
    return cursor


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


def ingest_event(db: Session, event: EventIn) -> tuple[bool, bool, Optional[int], dict]:
    existing = db.scalar(select(IncidentEvent).where(IncidentEvent.event_id == event.event_id))
    if existing is not None:
        return True, True, None, {}

    duplicate_problem = False
    if event.event_type == "problem":
        duplicate_problem = db.scalar(
            select(IncidentEvent).where(
                IncidentEvent.store_id == event.store_id,
                IncidentEvent.component == event.component,
                IncidentEvent.dedup_key == event.dedup_key,
                IncidentEvent.active.is_(True),
            )
        ) is not None

    closed_count = 0
    if event.event_type == "recovery":
        closed_count = _close_recoveries(db, event)

    incident = IncidentEvent(
        event_id=event.event_id,
        dedup_key=event.dedup_key,
        store_id=event.store_id,
        component=event.component,
        category=event.category,
        event_type=event.event_type,
        severity=event.severity,
        message=event.message,
        source=event.source,
        metadata_json=json.dumps(event.metadata),
        happened_at=_to_utc_naive(event.happened_at),
        active=should_mark_active(event.event_type) and not duplicate_problem,
    )
    db.add(incident)

    status = _entity_status(db, event.store_id, event.component)
    next_color = status_from_event(event.event_type, event.severity)
    status.active_incident_count = updated_count(
        status.active_incident_count,
        event.event_type,
        closed_for_entity=closed_count,
        deduplicated=duplicate_problem,
    )
    status.last_message = event.message
    status.last_event_id = event.event_id
    happened_at_naive = _to_utc_naive(event.happened_at)
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
            "category": event.category,
            "event_type": event.event_type,
            "severity": event.severity,
            "message": event.message,
            "source": event.source,
            "happened_at": happened_at_naive.isoformat(),
            "active": incident.active,
        },
        "status": {
            "store_id": status.store_id,
            "component": status.component,
            "status_color": status.status_color,
            "active_incident_count": status.active_incident_count,
            "last_message": status.last_message,
            "last_event_id": status.last_event_id,
            "last_changed_at": status.last_changed_at.isoformat(),
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
    return True, duplicate_problem, cursor.latest_sequence, payload


def bootstrap(db: Session, recent_limit: int) -> BootstrapOut:
    cursor = _cursor(db)

    statuses = db.scalars(
        select(EntityStatus).order_by(EntityStatus.status_color.desc(), EntityStatus.store_id.asc(), EntityStatus.component.asc())
    ).all()

    recent = db.scalars(
        select(IncidentEvent).order_by(IncidentEvent.happened_at.desc()).limit(recent_limit)
    ).all()

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
            )
            for s in statuses
        ],
        recent_events=[
            IncidentEventOut(
                event_id=e.event_id,
                dedup_key=e.dedup_key,
                store_id=e.store_id,
                component=e.component,
                category=e.category,
                event_type=e.event_type,
                severity=e.severity,
                message=e.message,
                source=e.source,
                happened_at=e.happened_at,
                active=e.active,
            )
            for e in recent
        ],
    )


def get_summary_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(EntityStatus.status_color, func.count(EntityStatus.id)).group_by(EntityStatus.status_color)).all()
    counts = {"green": 0, "yellow": 0, "red": 0}
    for color, count in rows:
        if color in counts:
            counts[color] = count
    return counts
