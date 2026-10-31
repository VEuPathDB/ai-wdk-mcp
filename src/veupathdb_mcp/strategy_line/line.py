from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol
from weakref import WeakValueDictionary

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from veupathdb.wdk import StrategyRequest, use_strategy_gate

_TAKE = text("SELECT pg_advisory_xact_lock(hashtextextended(:line, 0))")


class _Session(Protocol):
    async def execute(self, statement: Any, params: dict[str, str], /) -> Any: ...


type OpenSession = Callable[[], AbstractAsyncContextManager[_Session]]


def strategy_line_key(site_id: str, strategy_id: int) -> str:
    return f"wdk-strategy:{site_id}:{strategy_id}"


class StrategyLine:
    def __init__(self, open_session: OpenSession) -> None:
        self._open_session = open_session
        self._fronts: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def _front(self, key: str) -> asyncio.Lock:
        front = self._fronts.get(key)
        if front is None:
            front = asyncio.Lock()
            self._fronts[key] = front
        return front

    @asynccontextmanager
    async def hold(self, request: StrategyRequest) -> AsyncIterator[None]:
        key = strategy_line_key(request.site_id, request.strategy_id)
        async with self._front(key), self._open_session() as session:
            await session.execute(_TAKE, {"line": key})
            yield


def install_strategy_line(
    database_url: str,
    *,
    pool_size: int = 1,
    max_overflow: int = 0,
    pool_timeout: float | None = None,
) -> AsyncEngine:
    engine = create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
    )
    use_strategy_gate(StrategyLine(async_sessionmaker(engine)).hold)
    return engine
