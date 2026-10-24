from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from veupathdb.wdk import open_search_gate, use_search_gate

from veupathdb_mcp.search_line import (
    ExpensiveSearchLine,
    install_search_line,
    search_line_key,
)

_HELD = text(
    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted "
    "AND ((classid::bigint << 32) | objid::bigint) "
    "= ANY(SELECT hashtextextended(line, 0) FROM unnest(CAST(:lines AS text[])) AS line)"
)
_SECONDS = 10


@pytest.fixture(autouse=True)
def open_gate() -> Iterator[None]:
    use_search_gate(open_search_gate)
    yield
    use_search_gate(open_search_gate)


@pytest.fixture
async def watcher(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(make_url(database_url), poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def pooled(database_url: str) -> AsyncIterator[AsyncEngine]:
    url = make_url(database_url).render_as_string(hide_password=False)
    engine = install_search_line(url, pool_size=1, max_overflow=1)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _held(watcher: AsyncEngine, sites: list[str]) -> int:
    lines = [search_line_key(site) for site in sites]
    async with watcher.connect() as connection:
        held = await connection.scalar(_HELD, {"lines": lines})
    assert isinstance(held, int)
    return held


def _sites(count: int) -> list[str]:
    return [f"site-{uuid4().hex[:8]}" for _ in range(count)]


@dataclass
class _Search:
    line: ExpensiveSearchLine
    site_id: str
    arrivals: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self) -> None:
        async with self.line.hold(self.site_id):
            self.entered.set()
            self.arrivals.put_nowait(self.site_id)
            await self.release.wait()


async def _entered(arrivals: asyncio.Queue[str], count: int) -> None:
    async with asyncio.timeout(_SECONDS):
        for _ in range(count):
            await arrivals.get()


async def test_four_sites_at_once_hold_at_most_two_connections(
    pooled: AsyncEngine, watcher: AsyncEngine
) -> None:
    sites = _sites(4)
    line = ExpensiveSearchLine(pooled)
    arrivals: asyncio.Queue[str] = asyncio.Queue()
    searches = [_Search(line, site, arrivals) for site in sites]
    tasks = [asyncio.create_task(search.run()) for search in searches]

    await _entered(arrivals, 2)
    await asyncio.sleep(0.2)
    assert sum(search.entered.is_set() for search in searches) == 2
    assert pooled.pool.checkedout() == 2
    assert await _held(watcher, sites) == 2

    for search in searches:
        search.release.set()
    async with asyncio.timeout(_SECONDS):
        await asyncio.gather(*tasks)

    assert all(search.entered.is_set() for search in searches)
    assert pooled.pool.checkedout() == 0
    assert await _held(watcher, sites) == 0


async def test_a_search_that_fails_returns_its_connection_without_the_lock(
    pooled: AsyncEngine, watcher: AsyncEngine
) -> None:
    [site] = _sites(1)
    line = ExpensiveSearchLine(pooled)

    with pytest.raises(RuntimeError):
        async with line.hold(site):
            raise RuntimeError

    assert pooled.pool.checkedin() == 1
    assert await _held(watcher, [site]) == 0
    other = _Search(ExpensiveSearchLine(watcher), site)
    other.release.set()
    async with asyncio.timeout(_SECONDS):
        await other.run()
    assert other.entered.is_set() is True


async def test_a_cancelled_search_returns_its_connection_without_the_lock(
    pooled: AsyncEngine, watcher: AsyncEngine
) -> None:
    [site] = _sites(1)
    search = _Search(ExpensiveSearchLine(pooled), site)
    task = asyncio.create_task(search.run())
    await _entered(search.arrivals, 1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert pooled.pool.checkedout() == 0
    assert await _held(watcher, [site]) == 0
