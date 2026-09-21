from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from ..auth import get_current_user, require_ingest

router = APIRouter(prefix="/relate-config", tags=["relate"])

_KEY = "sauron:relate:config"

_aioredis = None


def _redis_client():
    global _aioredis
    if _aioredis is None:
        import redis.asyncio as aioredis

        from ..config import get_settings

        _aioredis = aioredis.from_url(get_settings().redis_url)
    return _aioredis


@router.get("")
async def get_relate_config(_: None = Depends(require_ingest)) -> dict:
    raw = await _redis_client().get(_KEY)
    return json.loads(raw) if raw else {}


@router.put("")
async def put_relate_config(config: dict, _: None = Depends(get_current_user)) -> dict:
    allowed = {
        "vocabulary",
        "fps",
        "score_threshold",
        "min_frames",
        "cooldown_s",
        "cameras",
        "enabled",
    }
    clean = {k: v for k, v in config.items() if k in allowed and v not in (None, "")}
    await _redis_client().set(_KEY, json.dumps(clean))
    return {"saved": len(clean), "applies_in_seconds": 10}
