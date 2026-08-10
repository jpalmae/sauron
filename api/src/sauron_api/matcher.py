from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AnalyticsEvent, Corridor

log = logging.getLogger(__name__)

_SIM_THRESHOLD = 0.80  # 64-dim HSV signature cosine


def _cos(a: list[float], b: list[float]) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return dot / (na**0.5 * nb**0.5)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def maybe_create_travel_time(
    session: AsyncSession, arrival: AnalyticsEvent
) -> AnalyticsEvent | None:
    """Match a LINE_CROSSING (with signature) against recent crossings at the
    upstream camera of a configured corridor; emit TRAVEL_TIME on a hit."""
    meta = arrival.extra or {}
    sig = meta.get("signature")
    if arrival.event_type != "LINE_CROSSING" or not isinstance(sig, list):
        return None

    result = await session.execute(
        select(Corridor).where(
            Corridor.to_camera_id == arrival.camera_id, Corridor.enabled.is_(True)
        )
    )
    for corridor in result.scalars().all():
        since = _aware(arrival.timestamp) - timedelta(seconds=corridor.max_travel_s)
        result2 = await session.execute(
            select(AnalyticsEvent)
            .where(
                AnalyticsEvent.camera_id == corridor.from_camera_id,
                AnalyticsEvent.event_type == "LINE_CROSSING",
                AnalyticsEvent.timestamp.between(since, _aware(arrival.timestamp)),
            )
            .order_by(AnalyticsEvent.timestamp.desc())
            .limit(200)
        )
        best: AnalyticsEvent | None = None
        best_sim = 0.0
        for dep in result2.scalars().all():
            dep_sig = (dep.extra or {}).get("signature")
            if not isinstance(dep_sig, list):
                continue
            sim = _cos(sig, dep_sig)
            if sim > best_sim:
                best, best_sim = dep, sim
        if best is None or best_sim < _SIM_THRESHOLD:
            continue

        travel_s = (_aware(arrival.timestamp) - _aware(best.timestamp)).total_seconds()
        if travel_s <= 0:
            continue
        speed_kmh = round(corridor.distance_m / travel_s * 3.6, 1)
        row = AnalyticsEvent(
            timestamp=arrival.timestamp,
            camera_id=corridor.to_camera_id,
            event_type="TRAVEL_TIME",
            priority="info",
            confidence=round(best_sim, 3),
            rule_id=f"corridor:{corridor.name}",
            object_id=arrival.object_id,
            vehicle_class=meta.get("vehicle_class"),
            extra={
                "corridor": corridor.name,
                "from_camera_id": str(corridor.from_camera_id),
                "to_camera_id": str(corridor.to_camera_id),
                "travel_time_s": round(travel_s, 1),
                "avg_speed_kmh": speed_kmh,
                "similarity": round(best_sim, 3),
                "vehicle_class": meta.get("vehicle_class"),
            },
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        log.info(
            "TRAVEL_TIME %s: %.1fs (%.1f km/h, sim %.2f)",
            corridor.name, travel_s, speed_kmh, best_sim,
        )
        return row
    return None
