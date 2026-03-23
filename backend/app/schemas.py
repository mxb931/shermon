from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


Severity = Literal["info", "warning", "critical"]
StatusColor = Literal["green", "yellow", "red", "purple", "white"]
EventType = Literal["problem", "recovery", "disable", "enable"]


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
    expected_green_interval_seconds: Optional[int] = Field(default=None, ge=1)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventAck(BaseModel):
    accepted: bool
    deduplicated: bool
    sequence: Optional[int] = None


class EntityStatusOut(BaseModel):
    store_id: str
    component: str
    status_color: StatusColor
    active_incident_count: int
    last_message: str
    last_event_id: str
    last_changed_at: datetime
    expected_green_interval_seconds: Optional[int] = None
    disabled: bool = False


class AckIn(BaseModel):
    event_id: str = Field(min_length=6, max_length=64)
    ack_message: str = Field(min_length=1, max_length=4000)
    expires_at: datetime
    ack_by: Optional[str] = Field(default=None, min_length=1, max_length=128)


class AckOut(BaseModel):
    event_id: str
    store_id: str
    component: str
    ack_message: str
    expires_at: datetime
    acknowledged_at: datetime
    ack_by: Optional[str] = None


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
    active_acks: list[AckOut]
