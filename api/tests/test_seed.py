import json

from sqlalchemy import select

from sauron_api.db import get_session_factory
from sauron_api.models import Camera
from sauron_api.seed import seed_cameras


def _seed_file(tmp_path, entries):
    p = tmp_path / "cameras.json"
    p.write_text(json.dumps(entries))
    return str(p)


async def test_seed_creates_cameras(tmp_path):
    path = _seed_file(
        tmp_path,
        [
            {"name": "Cam A", "stream_id": "seed-a", "rtsp_url": "rtsp://a"},
            {"name": "Cam B", "stream_id": "seed-b", "roi_config": {"lines": []}},
        ],
    )
    async with get_session_factory()() as session:
        created = await seed_cameras(session, path)
        assert created == 2

        result = await session.execute(select(Camera).where(Camera.stream_id == "seed-b"))
        cam = result.scalar_one()
        assert cam.roi_config == {"lines": []}
        assert cam.is_active is True


async def test_seed_is_idempotent_and_preserves_roi(tmp_path):
    path = _seed_file(tmp_path, [{"name": "Cam A", "stream_id": "seed-c"}])
    async with get_session_factory()() as session:
        await seed_cameras(session, path)
        # simulate ROI edited via configurator
        result = await session.execute(select(Camera).where(Camera.stream_id == "seed-c"))
        cam = result.scalar_one()
        cam.roi_config = {"polygons": [{"id": "p1"}]}
        await session.commit()

        # reseed with updated name and its own roi_config
        path2 = _seed_file(
            tmp_path,
            [{"name": "Cam A v2", "stream_id": "seed-c", "roi_config": {"lines": []}}],
        )
        created = await seed_cameras(session, path2)
        assert created == 0
        result = await session.execute(select(Camera).where(Camera.stream_id == "seed-c"))
        cam = result.scalar_one()
        assert cam.name == "Cam A v2"  # name refreshes
        assert cam.roi_config == {"polygons": [{"id": "p1"}]}  # roi preserved


async def test_seed_missing_file_warns_not_fails(tmp_path):
    async with get_session_factory()() as session:
        assert await seed_cameras(session, str(tmp_path / "nope.json")) == 0
