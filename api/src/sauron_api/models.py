from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONBCompat = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    stream_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    rtsp_url: Mapped[str] = mapped_column(String(255), default="")
    roi_config: Mapped[dict | None] = mapped_column(JSONBCompat, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    # TimescaleDB: unique constraints must include the partitioning column.
    __table_args__ = (UniqueConstraint("event_id", "timestamp"),)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    priority: Mapped[str] = mapped_column(String(20), default="info")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clip_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_id: Mapped[str] = mapped_column(String(100), default="")
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vehicle_class: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    extra: Mapped[dict | None] = mapped_column(JSONBCompat, nullable=True, name="metadata")
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class HourlyKpi(Base):
    __tablename__ = "hourly_kpis"

    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id"), primary_key=True)
    vehicle_class: Mapped[str] = mapped_column(String(50), primary_key=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    congestion_minutes: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
