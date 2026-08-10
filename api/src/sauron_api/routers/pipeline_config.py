from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_admin, require_ingest
from ..db import get_session
from ..models import EngineConfig

router = APIRouter(prefix="/pipeline-config", tags=["pipeline-config"])

# Seed matching the people-analytics defaults so the first poll is a no-op.
DEFAULTS_SEED: dict = {
    "confidence_threshold": 0.4,
    "nms_threshold": 0.45,
    "input_size": [640, 640],
    "detector": {"backend": "pose_objects"},
    "model": "yolov8n",
    "pose_onnx_path": "models/yolov8n-pose.onnx",
    "objects_onnx_path": "models/yolov8n.onnx",
    "classes": {
        "2": "car", "3": "motorcycle", "5": "bus", "7": "truck",
        "62": "chair", "63": "couch",
    },
    "tracker": {
        "high_thresh": 0.4, "low_thresh": 0.1, "match_thresh": 0.8,
        "max_time_lost": 30, "history_size": 60,
    },
    "capture": {"queue_size": 2, "use_gstreamer": False},
    "clips": {"enabled": True, "preroll_seconds": 6, "clip_fps": 10},
}


class EngineConfigUpdate(BaseModel):
    defaults: dict
    target_fps: int | None = None


async def _get_or_seed(session: AsyncSession) -> EngineConfig:
    ec = await session.get(EngineConfig, 1)
    if ec is None:
        ec = EngineConfig(id=1, defaults=DEFAULTS_SEED, target_fps=5, updated_at=datetime.now(UTC))
        session.add(ec)
        await session.commit()
    return ec


@router.get("")
async def get_engine_config(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_ingest),
):
    """Engine defaults for the inference poller (ingest token or admin JWT)."""
    ec = await _get_or_seed(session)
    return {
        "defaults": ec.defaults,
        "target_fps": ec.target_fps,
        "updated_at": ec.updated_at.isoformat() if ec.updated_at else None,
    }


@router.put("")
async def put_engine_config(
    payload: EngineConfigUpdate,
    session: AsyncSession = Depends(get_session),
    _: object = Depends(require_admin),
):
    """Update the engine defaults (admin). The inference reloads within ~15s."""
    ec = await _get_or_seed(session)
    ec.defaults = payload.defaults
    if payload.target_fps is not None:
        ec.target_fps = payload.target_fps
    ec.updated_at = datetime.now(UTC)
    await session.commit()
    return {
        "defaults": ec.defaults,
        "target_fps": ec.target_fps,
        "updated_at": ec.updated_at.isoformat() if ec.updated_at else None,
    }
