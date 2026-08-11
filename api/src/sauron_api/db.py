from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base

HYPERTABLE_DDL = """
CREATE EXTENSION IF NOT EXISTS timescaledb;
SELECT create_hypertable('analytics_events', 'timestamp', if_not_exists => TRUE);
SELECT create_hypertable('hourly_kpis', 'bucket', if_not_exists => TRUE);
"""

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=30,
            pool_timeout=30,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def init_db() -> None:
    """Idempotent bootstrap.

    PostgreSQL: schema is owned by Alembic (`alembic upgrade head` runs at
    container start); here we only ensure TimescaleDB hypertables exist.
    SQLite (tests/dev): plain create_all.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            for stmt in HYPERTABLE_DDL.strip().split(";"):
                if stmt.strip():
                    await conn.execute(text(stmt))
            settings = get_settings()
            if settings.retention_days > 0:
                await conn.execute(
                    text(
                        "SELECT add_retention_policy('analytics_events', "
                        f"INTERVAL '{int(settings.retention_days)} days', if_not_exists => TRUE)"
                    )
                )
        else:
            await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
