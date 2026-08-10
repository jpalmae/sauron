from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Camera

log = logging.getLogger(__name__)


async def seed_cameras(session: AsyncSession, path: str) -> int:
    """Upsert cameras from a JSON file (pre-provisioning).

    Existing cameras keep their roi_config (it may have been edited via the
    ROI configurator); only name/rtsp_url are refreshed.
    """
    file = Path(path)
    if not file.exists():
        log.warning("seed cameras file not found: %s", path)
        return 0
    entries = json.loads(file.read_text())
    created = 0
    for entry in entries:
        result = await session.execute(
            select(Camera).where(Camera.stream_id == entry["stream_id"])
        )
        camera = result.scalar_one_or_none()
        if camera is None:
            session.add(
                Camera(
                    name=entry["name"],
                    stream_id=entry["stream_id"],
                    rtsp_url=entry.get("rtsp_url", ""),
                    roi_config=entry.get("roi_config"),
                    is_active=entry.get("is_active", True),
                    latitude=entry.get("latitude"),
                    longitude=entry.get("longitude"),
                    detector=entry.get("detector"),
                    model=entry.get("model"),
                )
            )
            created += 1
        else:
            camera.name = entry["name"]
            camera.rtsp_url = entry.get("rtsp_url", camera.rtsp_url)
            camera.latitude = entry.get("latitude", camera.latitude)
            camera.longitude = entry.get("longitude", camera.longitude)
            if entry.get("detector") is not None:
                camera.detector = entry["detector"]
            if entry.get("model") is not None:
                camera.model = entry["model"]
            if camera.roi_config is None and entry.get("roi_config"):
                camera.roi_config = entry["roi_config"]
    await session.commit()
    if created:
        log.info("seeded %d cameras from %s", created, path)
    return created
