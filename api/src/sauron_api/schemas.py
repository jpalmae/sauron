from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    stream_id: str = Field(min_length=1, max_length=100)
    rtsp_url: str = ""
    roi_config: dict[str, Any] | None = None
    is_active: bool = True
    latitude: float | None = None
    longitude: float | None = None
    analytics_profile: Literal["traffic", "people"] = "traffic"


class CameraUpdate(BaseModel):
    name: str | None = None
    stream_id: str | None = Field(default=None, min_length=1, max_length=100)
    rtsp_url: str | None = None
    roi_config: dict[str, Any] | None = None
    is_active: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    analytics_profile: Literal["traffic", "people"] | None = None


class CameraRead(BaseModel):
    id: uuid.UUID
    name: str
    stream_id: str
    rtsp_url: str
    roi_config: dict[str, Any] | None
    is_active: bool
    latitude: float | None = None
    longitude: float | None = None
    analytics_profile: Literal["traffic", "people"] = "traffic"
    probe_status: Literal["untested", "ok", "failed"] = "untested"
    last_probe_at: datetime | None = None
    probe_details: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class EventIngest(BaseModel):
    """Payload published by the DeepStream video plane (Redis or direct POST)."""

    event_id: uuid.UUID | None = None
    event_type: str
    camera_id: str  # stream_id, resolved to cameras.id at ingest
    timestamp: float
    confidence: float = 0.0
    priority: str = "info"
    rule_id: str = ""
    object_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    snapshot_jpeg: str | None = None  # base64
    clip_mp4: str | None = None  # base64


class EventRead(BaseModel):
    event_id: uuid.UUID
    timestamp: datetime
    camera_id: uuid.UUID
    event_type: str
    priority: str
    confidence: float | None
    rule_id: str
    object_id: int | None
    metadata: dict[str, Any] | None
    snapshot_url: str | None = None
    clip_url: str | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None

    model_config = {"from_attributes": True}


class EventPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[EventRead]


class KpiRow(BaseModel):
    bucket: datetime
    camera_id: uuid.UUID
    vehicle_class: str | None
    total_count: int
    avg_speed_kmh: float | None
    congestion_minutes: float


class BrandingRead(BaseModel):
    app_name: str
    company_name: str
    logo_light_url: str
    logo_dark_url: str
    favicon_url: str
    primary_color: str
    accent_color: str
    support_url: str
    auth_required: bool = False
    sso_providers: list[str] = []
