from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/models", tags=["models"])

# Mirror of the inference model catalog (inference/models.py). Kept small and
# static: the catalog changes only with a release.
CATALOG = [
    {"name": "yolov8n", "family": "yolov8", "size_mb": 13, "profile": "XS"},
    {"name": "yolov8s", "family": "yolov8", "size_mb": 45, "profile": "XS/S"},
    {"name": "yolov8m", "family": "yolov8", "size_mb": 104, "profile": "S/M"},
    {"name": "yolo11n", "family": "yolo11", "size_mb": 11, "profile": "XS"},
    {"name": "yolo11s", "family": "yolo11", "size_mb": 38, "profile": "XS/S"},
    {"name": "yolov8n-pose", "family": "yolov8-pose", "size_mb": 13, "profile": "XS"},
]

BACKENDS = ["onnx", "pose_objects", "tensorrt", "openai", "mock"]


@router.get("")
async def list_models(_: User = Depends(get_current_user)):
    """Model catalog for per-camera rollout (OTA)."""
    return {"models": CATALOG, "backends": BACKENDS}
