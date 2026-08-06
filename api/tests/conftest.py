import os

os.environ.setdefault("SAURON_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SAURON_CONSUMER_ENABLED", "false")
os.environ.setdefault("SAURON_BRANDING_APP_NAME", "TestBrand")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sauron_api.db import init_db
from sauron_api.main import app


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_db():
    await init_db()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
