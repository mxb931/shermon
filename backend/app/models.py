from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    dedup_key: Mapped[str] = mapped_column(String(128), index=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(128), index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    happened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class EntityStatus(Base):
    __tablename__ = "entity_status"
    __table_args__ = (UniqueConstraint("store_id", "component", name="uq_status_entity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(128), index=True)
    status_color: Mapped[str] = mapped_column(String(16), index=True)
    active_incident_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message: Mapped[str] = mapped_column(Text, default="")
    last_event_id: Mapped[str] = mapped_column(String(64), default="")
    last_changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StreamCursor(Base):
    __tablename__ = "stream_cursor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    latest_sequence: Mapped[int] = mapped_column(Integer, default=0)


class BroadcastEvent(Base):
    __tablename__ = "broadcast_events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
