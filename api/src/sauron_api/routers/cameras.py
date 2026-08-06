from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Camera
from ..schemas import CameraCreate, CameraRead, CameraUpdate

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=list[CameraRead])
async def list_cameras(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Camera).order_by(Camera.name))
    return result.scalars().all()


@router.post("", response_model=CameraRead, status_code=201)
async def create_camera(payload: CameraCreate, session: AsyncSession = Depends(get_session)):
    exists = await session.execute(select(Camera).where(Camera.stream_id == payload.stream_id))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(409, f"stream_id '{payload.stream_id}' already exists")
    camera = Camera(**payload.model_dump())
    session.add(camera)
    await session.commit()
    await session.refresh(camera)
    return camera


@router.get("/{camera_id}", response_model=CameraRead)
async def get_camera(camera_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(404, "camera not found")
    return camera


@router.patch("/{camera_id}", response_model=CameraRead)
async def update_camera(
    camera_id: uuid.UUID, payload: CameraUpdate, session: AsyncSession = Depends(get_session)
):
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(404, "camera not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(camera, field, value)
    await session.commit()
    await session.refresh(camera)
    return camera


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(404, "camera not found")
    await session.delete(camera)
    await session.commit()
