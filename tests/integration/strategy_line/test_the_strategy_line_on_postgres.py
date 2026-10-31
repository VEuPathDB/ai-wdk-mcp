from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from veupathdb.wdk import StrategyRequest

from veupathdb_mcp.strategy_line import StrategyLine, strategy_line_key

_WAITERS = text(
    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
    "AND ((classid::bigint << 32) | objid::bigint) = hashtextextended(:line, 0)"
)
_SECONDS = 10


@pytest.fixture
async def engines(database_url: str) -> AsyncIterator[list[AsyncEngine]]:
    made = [
        create_async_engine(make_url(database_url), poolclass=NullPool)
        for _ in range(3)
    ]
    try:
        yield made
    finally:
        for engine in made:
            await engine.dispose()


def _line(engine: AsyncEngine) -> StrategyLine:
    return StrategyLine(async_sessionmaker(engine))


async def _one_waiter(engine: AsyncEngine, key: str) -> None:
    async with asyncio.timeout(_SECONDS), engine.connect() as connection:
        while True:
            if await connection.scalar(_WAITERS, {"line": key}) == 1:
                return
            await asyncio.sleep(0.01)


async def test_a_second_process_waits_for_the_strategy_until_the_first_ends(
    engines: list[AsyncEngine],
) -> None:
    first_process, second_process, observer = engines
    request = StrategyRequest(site_id="plasmodb", strategy_id=214644620)
    key = strategy_line_key("plasmodb", 214644620)
    order: list[str] = []
    release = asyncio.Event()
    entered = asyncio.Event()

    async def first() -> None:
        async with _line(first_process).hold(request):
            order.append("first")
            entered.set()
            await release.wait()

    async def second() -> None:
        async with _line(second_process).hold(request):
            order.append("second")

    holding = asyncio.create_task(first())
    await entered.wait()
    waiting = asyncio.create_task(second())
    await _one_waiter(observer, key)
    order_while_held = list(order)
    release.set()
    await asyncio.gather(holding, waiting)

    assert order_while_held == ["first"]
    assert order == ["first", "second"]


async def test_another_strategy_does_not_wait(engines: list[AsyncEngine]) -> None:
    first_process, second_process, _ = engines
    release = asyncio.Event()
    entered = asyncio.Event()

    async def first() -> None:
        async with _line(first_process).hold(
            StrategyRequest(site_id="plasmodb", strategy_id=1)
        ):
            entered.set()
            await release.wait()

    holding = asyncio.create_task(first())
    await entered.wait()
    async with asyncio.timeout(_SECONDS):
        async with _line(second_process).hold(
            StrategyRequest(site_id="plasmodb", strategy_id=2)
        ):
            other_entered = True
    release.set()
    await holding

    assert other_entered is True
