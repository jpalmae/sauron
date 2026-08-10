from __future__ import annotations

from fastapi import APIRouter

from ..config import get_branding, get_settings
from ..oidc import get_providers
from ..schemas import BrandingRead

router = APIRouter(prefix="/branding", tags=["branding"])


@router.get("", response_model=BrandingRead)
async def get_branding_config():
    """Public white-label config consumed by the frontend before first render."""
    data = BrandingRead.model_validate(get_branding(), from_attributes=True)
    data.auth_required = get_settings().auth_enabled
    data.sso_providers = list(get_providers())
    return data
