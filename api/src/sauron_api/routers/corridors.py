from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_admin
from ..db import get_session
from ..models import Corridor, User

router = APIRouter(prefix="/corridors", tags=["corridors"])


class CorridorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    from_camera_id: uuid.UUID
    to_camera_id: uuid.UUID
    distance_m: float = Field(gt=0)
    max_travel_s: int = 7200
    enabled: bool = True


class CorridorUpdate(BaseModel):
    name: str | None = None
    distance_m: float | None = None
    max_travel_s: int | None = None
    enabled: bool | None = None


def _read(c: Corridor) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "from_camera_id": str(c.from_camera_id),
        "to_camera_id": str(c.to_camera_id),
        "distance_m": c.distance_m,
        "max_travel_s": c.max_travel_s,
        "enabled": c.enabled,
    }


@router.get("")
async def list_corridors(
    session: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)
):
    result = await session.execute(select(Corridor).order_by(Corridor.name))
    return [_read(c) for c in result.scalars().all()]


@router.post("", status_code=201)
async def create_corridor(
    payload: CorridorCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    if payload.from_camera_id == payload.to_camera_id:
        raise HTTPException(422, "from/to must be different cameras")
    c = Corridor(**payload.model_dump())
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return _read(c)


@router.patch("/{corridor_id}")
async def update_corridor(
    corridor_id: uuid.UUID,
    payload: CorridorUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    c = await session.get(Corridor, corridor_id)
    if c is None:
        raise HTTPException(404, "corridor not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    await session.commit()
    await session.refresh(c)
    return _read(c)


@router.delete("/{corridor_id}", status_code=204)
async def delete_corridor(
    corridor_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    c = await session.get(Corridor, corridor_id)
    if c is None:
        raise HTTPException(404, "corridor not found")
    await session.delete(c)
    await session.commit()
