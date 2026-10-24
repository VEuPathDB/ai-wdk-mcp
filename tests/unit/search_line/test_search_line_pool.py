from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.pool import AsyncAdaptedQueuePool
from veupathdb.wdk import open_search_gate, search_gate, use_search_gate

from veupathdb_mcp.search_line import install_search_line

_URL = "postgresql+asyncpg://line@db.invalid/line"


@pytest.fixture(autouse=True)
def open_gate() -> Iterator[None]:
    use_search_gate(open_search_gate)
    yield
    use_search_gate(open_search_gate)


async def test_the_line_engine_holds_one_connection_and_waits_without_a_limit() -> None:
    engine = install_search_line(_URL)
    try:
        assert isinstance(engine.pool, AsyncAdaptedQueuePool)
        assert engine.pool.size() == 1
        assert engine.pool.timeout() is None
        assert search_gate() is not open_search_gate
    finally:
        await engine.dispose()


async def test_the_line_engine_takes_the_sizes_it_is_given() -> None:
    engine = install_search_line(_URL, pool_size=3, max_overflow=0, pool_timeout=45.0)
    try:
        assert engine.pool.size() == 3
        assert engine.pool.timeout() == pytest.approx(45.0)
    finally:
        await engine.dispose()
