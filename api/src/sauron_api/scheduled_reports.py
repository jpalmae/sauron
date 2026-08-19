from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import get_settings
from .db import get_session_factory
from .models import AnalyticsEvent, Camera, NotificationDelivery, ReportSchedule
from .storage import get_storage

log = logging.getLogger(__name__)


def next_report_run(
    frequency: str,
    hour: int,
    minute: int,
    timezone_name: str,
    after: datetime | None = None,
) -> datetime:
    if frequency not in {"daily", "weekly", "monthly"}:
        raise ValueError("frequency must be daily, weekly or monthly")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise ValueError("unknown timezone") from None
    now = (after or datetime.now(UTC)).astimezone(zone)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if frequency == "weekly":
        candidate -= timedelta(days=candidate.weekday())
    elif frequency == "monthly":
        candidate = candidate.replace(day=1)
    if candidate <= now:
        if frequency == "daily":
            candidate += timedelta(days=1)
        elif frequency == "weekly":
            candidate += timedelta(days=7)
        else:
            year = candidate.year + (1 if candidate.month == 12 else 0)
            month = 1 if candidate.month == 12 else candidate.month + 1
            candidate = candidate.replace(year=year, month=month, day=1)
    return candidate.astimezone(UTC)


def report_period_start(frequency: str, now: datetime) -> datetime:
    if frequency == "daily":
        return now - timedelta(days=1)
    if frequency == "weekly":
        return now - timedelta(days=7)
    return now - timedelta(days=31)


async def run_report_scheduler() -> None:
    while True:
        try:
            await process_due_reports()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduled reports worker failed")
        await asyncio.sleep(get_settings().report_worker_seconds)


async def process_due_reports(limit: int = 20) -> int:
    now = datetime.now(UTC)
    produced = 0
    async with get_session_factory()() as session:
        query = (
            select(ReportSchedule)
            .where(ReportSchedule.enabled.is_(True), ReportSchedule.next_run_at <= now)
            .order_by(ReportSchedule.next_run_at)
            .limit(limit)
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        schedules = list((await session.execute(query)).scalars().all())
        for schedule in schedules:
            since = report_period_start(schedule.frequency, now)
            content, total = await build_events_report(session, since, now, schedule.camera_id)
            key = await get_storage().upload_report(schedule.id, now, content)
            if key is None:
                log.error("report %s was not scheduled because storage upload failed", schedule.id)
                continue
            report_url = await get_storage().presigned_url(key)
            if report_url is None:
                log.error("report %s was uploaded but could not be signed", schedule.id)
                continue
            period = f"{since.date()}:{now.date()}"
            delivery = NotificationDelivery(
                channel_id=schedule.channel_id,
                event_id=None,
                dedupe_key=f"report:{schedule.id}:{period}",
                status="pending",
                next_attempt_at=now,
                payload={
                    "event_id": f"report-{schedule.id}-{now.date()}",
                    "event_type": "SCHEDULED_REPORT",
                    "priority": "info",
                    "camera": str(schedule.camera_id or "all"),
                    "timestamp": now.isoformat(),
                    "rule_id": schedule.name,
                    "metadata": {
                        "frequency": schedule.frequency,
                        "events": total,
                        "period_start": since.isoformat(),
                        "period_end": now.isoformat(),
                        "report_url": report_url,
                    },
                    "report_url": report_url,
                },
            )
            try:
                async with session.begin_nested():
                    session.add(delivery)
                    await session.flush()
            except IntegrityError:
                pass
            schedule.last_run_at = now
            schedule.next_run_at = next_report_run(
                schedule.frequency, schedule.hour, schedule.minute, schedule.timezone, after=now
            )
            produced += 1
        await session.commit()
    return produced


async def build_events_report(session, since, until, camera_id=None) -> tuple[bytes, int]:
    query = (
        select(AnalyticsEvent, Camera.stream_id)
        .join(Camera, Camera.id == AnalyticsEvent.camera_id)
        .where(AnalyticsEvent.timestamp >= since, AnalyticsEvent.timestamp < until)
        .order_by(AnalyticsEvent.timestamp)
    )
    if camera_id:
        query = query.where(AnalyticsEvent.camera_id == camera_id)
    rows = list((await session.execute(query)).all())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["timestamp", "camera", "event_type", "priority", "rule_id", "object_id", "confidence"]
    )
    for event, stream_id in rows:
        writer.writerow(
            [
                event.timestamp.isoformat(),
                stream_id,
                event.event_type,
                event.priority,
                event.rule_id,
                event.object_id,
                event.confidence,
            ]
        )
    return output.getvalue().encode("utf-8-sig"), len(rows)
