from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from sauron_api.config import get_settings
from sauron_api.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url)

    async def _run() -> None:
        async with engine.connect() as conn:
            await conn.run_sync(do_run_migrations)
        await engine.dispose()

    asyncio.run(_run())


run_migrations_online()
