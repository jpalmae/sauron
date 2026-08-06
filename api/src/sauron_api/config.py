from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BrandingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAURON_BRANDING_")

    app_name: str = "Sauron"
    company_name: str = ""
    logo_light_url: str = "/brand/logo-light.svg"
    logo_dark_url: str = "/brand/logo-dark.svg"
    favicon_url: str = "/brand/favicon.ico"
    primary_color: str = "#0E7C66"
    accent_color: str = "#F59E0B"
    support_url: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAURON_")

    database_url: str = "postgresql+asyncpg://sauron:sauron@localhost:5432/sauron"
    redis_url: str = "redis://localhost:6379/0"
    redis_events_channel: str = "sauron:events"
    consumer_enabled: bool = True

    s3_endpoint: str = ""  # empty disables snapshot storage (dev)
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "sauron-events"
    s3_secure: bool = False

    cors_origins: list[str] = ["http://localhost:5173"]


_settings: Settings | None = None
_branding: BrandingSettings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_branding() -> BrandingSettings:
    global _branding
    if _branding is None:
        _branding = BrandingSettings()
    return _branding
