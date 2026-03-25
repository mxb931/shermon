from datetime import datetime
import re
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Severity = Literal["info", "warning", "critical"]
StatusColor = Literal["green", "yellow", "red", "purple", "white"]
EventType = Literal["problem", "ok", "disable", "enable"]


_STALE_INTERVAL_RE = re.compile(r"^(?:\d+[dhm])+$")
_STALE_INTERVAL_PART_RE = re.compile(r"(\d+)([dhm])")


def parse_stale_interval_seconds(value: str) -> int:
    raw = (value or "").strip().lower()
    if not raw:
        raise ValueError("stale_interval must not be empty")
    if not _STALE_INTERVAL_RE.fullmatch(raw):
        raise ValueError("stale_interval must use only d, h, m segments like 2d5h10m")

    seconds = 0
    for amount_text, unit in _STALE_INTERVAL_PART_RE.findall(raw):
        amount = int(amount_text)
        if amount <= 0:
            raise ValueError("stale_interval segment values must be positive integers")
        if unit == "d":
            seconds += amount * 86400
        elif unit == "h":
            seconds += amount * 3600
        else:
            seconds += amount * 60
    return seconds


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=6, max_length=64)
    dedup_key: str = Field(min_length=3, max_length=128)
    store_id: str = Field(min_length=1, max_length=64)
    component: str = Field(min_length=1, max_length=128)
    event_type: EventType
    severity: Severity
    message: str = Field(min_length=1, max_length=4000)
    source: str = Field(min_length=1, max_length=128)
    stale_interval: Optional[str] = Field(default=None, min_length=2, max_length=32)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type", mode="before")
    @classmethod
    def normalize_legacy_recovery(cls, value):
        if isinstance(value, str) and value.strip().lower() == "recovery":
            return "ok"
        return value

    @model_validator(mode="after")
    def validate_severity_for_event_type(self):
        allowed = {
            "problem": {"warning", "critical"},
            "ok": {"info"},
            "enable": {"info"},
            "disable": {"info"},
        }
        if self.severity not in allowed[self.event_type]:
            allowed_values = ", ".join(sorted(allowed[self.event_type]))
            raise ValueError(
                f"severity '{self.severity}' is invalid for event_type '{self.event_type}'; "
                f"allowed severities: {allowed_values}"
            )
        if self.stale_interval is not None:
            parse_stale_interval_seconds(self.stale_interval)
        return self


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
    stale_interval_seconds: Optional[int] = None
    disabled: bool = False


class StoreStatusOut(BaseModel):
    store_id: str
    status_color: StatusColor
    component_count: int
    active_incident_count: int


class ComponentStatusOut(BaseModel):
    store_id: str
    component: str
    status_color: StatusColor
    active_incident_count: int
    last_message: str
    last_event_id: str
    last_changed_at: datetime
    stale_interval_seconds: Optional[int] = None
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
