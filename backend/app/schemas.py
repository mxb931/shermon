from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


Severity = Literal["info", "warning", "critical"]
EventType = Literal["problem", "recovery"]


class EventIn(BaseModel):
    event_id: str = Field(min_length=6, max_length=64)
    dedup_key: str = Field(min_length=3, max_length=128)
    store_id: str = Field(min_length=1, max_length=64)
    component: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    event_type: EventType
    severity: Severity
    message: str = Field(min_length=1, max_length=4000)
    source: str = Field(min_length=1, max_length=128)
    happened_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventAck(BaseModel):
    accepted: bool
    deduplicated: bool
    sequence: Optional[int] = None


class EntityStatusOut(BaseModel):
    store_id: str
    component: str
    status_color: str
    active_incident_count: int
    last_message: str
    last_event_id: str
    last_changed_at: datetime


class IncidentEventOut(BaseModel):
    event_id: str
    dedup_key: str
    store_id: str
    component: str
    category: str
    event_type: str
    severity: str
    message: str
    source: str
    happened_at: datetime
    active: bool


class BootstrapOut(BaseModel):
    latest_sequence: int
    statuses: list[EntityStatusOut]
    recent_events: list[IncidentEventOut]
