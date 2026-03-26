from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
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
    event_type: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(128), index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    happened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
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
    stale_interval_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_checkin_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    disabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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


class Acknowledgement(Base):
    __tablename__ = "acknowledgements"
    __table_args__ = (Index("ix_ack_active_expires", "active", "expires_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    store_id: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(128), index=True)
    ack_message: Mapped[str] = mapped_column(Text)
    ack_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class RuntimeConfig(Base):
    __tablename__ = "runtime_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sweeper_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    entity_history_default_limit: Mapped[int] = mapped_column(Integer, default=1000)
    entity_history_limit_options_json: Mapped[str] = mapped_column(Text, default="[250,500,1000,2000]")
    log_max_mb: Mapped[int] = mapped_column(Integer, default=50)
    log_backup_count: Mapped[int] = mapped_column(Integer, default=20)


class RetiredStore(Base):
    __tablename__ = "retired_store"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    retired_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RetiredComponent(Base):
    __tablename__ = "retired_component"
    __table_args__ = (UniqueConstraint("store_id", "component", name="uq_retired_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    retired_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
