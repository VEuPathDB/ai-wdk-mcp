from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from veupathdb import get_logger, get_observer
from veupathdb.wdk import (
    SearchGate,
    SearchRequest,
    runs_an_expensive_search,
    use_search_gate,
)

logger = get_logger(__name__)

NOTICE_SECONDS = 5.0

_TAKE = text("SELECT pg_advisory_lock(hashtextextended(:line, 0))")
_RELEASE = text("SELECT pg_advisory_unlock(hashtextextended(:line, 0))")

type ExpensiveSearch = Callable[[SearchRequest], bool]


def search_line_key(site_id: str) -> str:
    return f"wdk-expensive-search:{site_id}"


class SearchLine(Protocol):
    def hold(self, site_id: str) -> AbstractAsyncContextManager[None]: ...


class SearchWaitListener(Protocol):
    async def waiting(self, site_id: str) -> None: ...

    async def running(self, site_id: str) -> None: ...


_listener: ContextVar[SearchWaitListener | None] = ContextVar(
    "veupathdb_mcp_search_wait_listener", default=None
)


@contextmanager
def told_while_waiting(listener: SearchWaitListener) -> Iterator[None]:
    reset = _listener.set(listener)
    try:
        yield
    finally:
        _listener.reset(reset)


class ExpensiveSearchLine:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._fronts: dict[str, asyncio.Lock] = {}

    def _front(self, site_id: str) -> asyncio.Lock:
        front = self._fronts.get(site_id)
        if front is None:
            front = asyncio.Lock()
            self._fronts[site_id] = front
        return front

    @asynccontextmanager
    async def hold(self, site_id: str) -> AsyncIterator[None]:
        line = {"line": search_line_key(site_id)}
        async with self._front(site_id), self._engine.connect() as connection:
            await connection.execute(_TAKE, line)
            yield
            await connection.execute(_RELEASE, line)


class _Told:
    def __init__(
        self, listener: SearchWaitListener | None, site_id: str, notice_seconds: float
    ) -> None:
        self.listener = listener
        self.site_id = site_id
        self.notice_seconds = notice_seconds
        self.sent = False

    async def after_a_while(self) -> None:
        if self.listener is None:
            return
        await asyncio.sleep(self.notice_seconds)
        self.sent = True
        await asyncio.shield(self.listener.waiting(self.site_id))

    async def ended(self, waited: float) -> None:
        get_observer().on_wdk_search_wait(
            waited, {"site": self.site_id, "line": "expensive"}
        )
        if waited >= self.notice_seconds:
            logger.info(
                "A search waited for the expensive-search line",
                site_id=self.site_id,
                waited_seconds=round(waited, 1),
            )
        if self.sent and self.listener is not None:
            await self.listener.running(self.site_id)


@asynccontextmanager
async def _held(
    line: SearchLine, site_id: str, notice_seconds: float
) -> AsyncIterator[None]:
    told = _Told(_listener.get(), site_id, notice_seconds)
    start = time.monotonic()
    telling = asyncio.create_task(told.after_a_while())
    try:
        async with line.hold(site_id):
            telling.cancel()
            await told.ended(time.monotonic() - start)
            yield
    finally:
        telling.cancel()


def search_line_gate(
    line: SearchLine,
    expensive: ExpensiveSearch = runs_an_expensive_search,
    notice_seconds: float = NOTICE_SECONDS,
) -> SearchGate:
    @asynccontextmanager
    async def gate(request: SearchRequest) -> AsyncIterator[None]:
        if not expensive(request):
            yield
            return
        async with _held(line, request.site_id, notice_seconds):
            yield

    return gate


def install_search_line(
    database_url: str, expensive: ExpensiveSearch = runs_an_expensive_search
) -> None:
    engine = create_async_engine(
        database_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    use_search_gate(search_line_gate(ExpensiveSearchLine(engine), expensive))
