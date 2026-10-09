from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from veupathdb_mcp.search_line import ExpensiveSearchLine, search_line_key

_WAITERS = text(
    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
    "AND ((classid::bigint << 32) | objid::bigint) = hashtextextended(:line, 0)"
)
_SECONDS = 10


@pytest.fixture
async def engines(database_url: str) -> AsyncIterator[list[AsyncEngine]]:
    made = [
        create_async_engine(
            make_url(database_url), poolclass=NullPool, isolation_level="AUTOCOMMIT"
        )
        for _ in range(5)
    ]
    try:
        yield made
    finally:
        for engine in made:
            await engine.dispose()


def _site() -> str:
    return f"site-{uuid4().hex[:8]}"


async def _waiters(engine: AsyncEngine, site_id: str, count: int) -> None:
    line = {"line": search_line_key(site_id)}
    async with asyncio.timeout(_SECONDS), engine.connect() as connection:
        while True:
            if await connection.scalar(_WAITERS, line) == count:
                return
            await asyncio.sleep(0.01)


@dataclass
class _Holder:
    line: ExpensiveSearchLine
    site_id: str
    order: list[str] = field(default_factory=list)
    name: str = ""
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self) -> None:
        async with self.line.hold(self.site_id):
            self.order.append(self.name)
            self.entered.set()
            await self.release.wait()

    def start(self) -> asyncio.Task[None]:
        return asyncio.create_task(self.run())


async def test_two_processes_hold_one_site_one_after_the_other(
    engines: list[AsyncEngine],
) -> None:
    site_id = _site()
    first = _Holder(ExpensiveSearchLine(engines[0]), site_id)
    second = _Holder(ExpensiveSearchLine(engines[1]), site_id)
    holding = first.start()
    await first.entered.wait()

    waiting = second.start()
    await _waiters(engines[4], site_id, 1)
    assert second.entered.is_set() is False

    first.release.set()
    await holding
    async with asyncio.timeout(_SECONDS):
        await second.entered.wait()
    second.release.set()
    await waiting


async def test_two_sites_are_held_side_by_side(engines: list[AsyncEngine]) -> None:
    plasmo = _Holder(ExpensiveSearchLine(engines[0]), _site())
    toxo = _Holder(ExpensiveSearchLine(engines[1]), _site())
    tasks = [plasmo.start(), toxo.start()]

    async with asyncio.timeout(_SECONDS):
        await plasmo.entered.wait()
        await toxo.entered.wait()

    plasmo.release.set()
    toxo.release.set()
    await asyncio.gather(*tasks)


async def test_a_cancelled_waiter_does_not_hold_up_the_next(
    engines: list[AsyncEngine],
) -> None:
    site_id = _site()
    first = _Holder(ExpensiveSearchLine(engines[0]), site_id)
    gone = _Holder(ExpensiveSearchLine(engines[1]), site_id)
    third = _Holder(ExpensiveSearchLine(engines[2]), site_id)
    holding = first.start()
    await first.entered.wait()
    cancelled = gone.start()
    await _waiters(engines[4], site_id, 1)
    waiting = third.start()
    await _waiters(engines[4], site_id, 2)

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    await _waiters(engines[4], site_id, 1)
    first.release.set()
    await holding

    async with asyncio.timeout(_SECONDS):
        await third.entered.wait()
    third.release.set()
    await waiting
    assert gone.entered.is_set() is False


async def test_a_holder_whose_connection_dies_frees_the_line(
    engines: list[AsyncEngine],
) -> None:
    site_id = _site()
    async with engines[0].connect() as crashed:
        await crashed.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:line, 0))"),
            {"line": search_line_key(site_id)},
        )
        pid = await crashed.scalar(text("SELECT pg_backend_pid()"))
        waiter = _Holder(ExpensiveSearchLine(engines[1]), site_id)
        waiting = waiter.start()
        await _waiters(engines[4], site_id, 1)

        async with engines[2].connect() as admin:
            await admin.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})

        async with asyncio.timeout(_SECONDS):
            await waiter.entered.wait()
        waiter.release.set()
        await waiting
        await crashed.invalidate()


async def test_waiters_from_four_processes_take_the_line_in_arrival_order(
    engines: list[AsyncEngine],
) -> None:
    site_id = _site()
    order: list[str] = []
    holders = [
        _Holder(ExpensiveSearchLine(engine), site_id, order, name)
        for engine, name in zip(engines[:4], ("a", "b", "c", "d"), strict=True)
    ]
    tasks = [holders[0].start()]
    await holders[0].entered.wait()
    for queued, holder in enumerate(holders[1:], start=1):
        tasks.append(holder.start())
        await _waiters(engines[4], site_id, queued)

    for holder in holders:
        async with asyncio.timeout(_SECONDS):
            await holder.entered.wait()
        holder.release.set()
    await asyncio.gather(*tasks)

    assert order == ["a", "b", "c", "d"]


async def test_one_process_queues_its_own_waiters_in_order_on_one_connection(
    engines: list[AsyncEngine],
) -> None:
    site_id = _site()
    line = ExpensiveSearchLine(engines[0])
    order: list[str] = []
    holders = [_Holder(line, site_id, order, name) for name in ("a", "b", "c")]
    tasks = [holder.start() for holder in holders]
    await holders[0].entered.wait()
    await _waiters(engines[4], site_id, 0)

    for holder in holders:
        async with asyncio.timeout(_SECONDS):
            await holder.entered.wait()
        holder.release.set()
    await asyncio.gather(*tasks)

    assert order == ["a", "b", "c"]
