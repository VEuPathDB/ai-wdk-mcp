from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import exc
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from veupathdb_mcp.embeddings import db


@pytest.fixture
async def own_engine(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    url = make_url(database_url).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("EMBEDDING_DB_POOL_SIZE", "1")
    monkeypatch.setenv("EMBEDDING_DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("EMBEDDING_DB_POOL_TIMEOUT_SECONDS", "0.5")
    db._own.maker = None
    yield
    maker = db._own.maker
    db._own.maker = None
    assert maker is not None
    engine = maker.kw["bind"]
    assert isinstance(engine, AsyncEngine)
    await engine.dispose()


@pytest.mark.usefixtures("own_engine")
async def test_the_own_engine_opens_no_more_than_its_pool_and_overflow() -> None:
    first = db._own_session()
    second = db._own_session()
    third = db._own_session()
    try:
        await first.connection()
        await second.connection()
        with pytest.raises(exc.TimeoutError):
            await third.connection()
    finally:
        await first.close()
        await second.close()
        await third.close()
