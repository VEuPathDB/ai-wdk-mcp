from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import TracebackType

import pytest
from veupathdb.wdk import (
    StrategyRequest,
    open_strategy_gate,
    strategy_gate,
    use_strategy_gate,
)

from veupathdb_mcp.strategy_line import (
    StrategyLine,
    install_strategy_line,
    strategy_line_key,
)


class _Session:
    def __init__(self, sessions: _Sessions) -> None:
        self.sessions = sessions

    async def __aenter__(self) -> _Session:
        self.sessions.open += 1
        self.sessions.most_open = max(self.sessions.most_open, self.sessions.open)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.sessions.open -= 1

    async def execute(self, _statement: object, params: dict[str, str]) -> None:
        self.sessions.keys.append(params["line"])


class _Sessions:
    def __init__(self) -> None:
        self.open = 0
        self.most_open = 0
        self.keys: list[str] = []

    def __call__(self) -> _Session:
        return _Session(self)


def _request(strategy_id: int) -> StrategyRequest:
    return StrategyRequest(site_id="plasmodb", strategy_id=strategy_id)


@pytest.fixture
def restored_gate() -> Iterator[None]:
    previous = strategy_gate()
    try:
        yield
    finally:
        use_strategy_gate(previous)


def test_the_key_names_the_site_and_the_strategy() -> None:
    assert strategy_line_key("plasmodb", 214644620) == "wdk-strategy:plasmodb:214644620"


async def test_a_hold_takes_the_strategys_key() -> None:
    sessions = _Sessions()

    async with StrategyLine(sessions).hold(_request(214644620)):
        pass

    assert sessions.keys == ["wdk-strategy:plasmodb:214644620"]


async def test_two_requests_on_one_strategy_hold_one_session_at_a_time() -> None:
    sessions = _Sessions()
    line = StrategyLine(sessions)
    release = asyncio.Event()

    async def held() -> None:
        async with line.hold(_request(214644620)):
            await release.wait()

    first = asyncio.create_task(held())
    second = asyncio.create_task(held())
    for _ in range(10):
        await asyncio.sleep(0)
    open_while_held = sessions.open
    release.set()
    await asyncio.gather(first, second)

    assert (open_while_held, sessions.most_open, len(sessions.keys)) == (1, 1, 2)


async def test_two_strategies_hold_their_lines_side_by_side() -> None:
    sessions = _Sessions()
    line = StrategyLine(sessions)
    release = asyncio.Event()

    async def held(strategy_id: int) -> None:
        async with line.hold(_request(strategy_id)):
            await release.wait()

    tasks = [asyncio.create_task(held(n)) for n in (1, 2)]
    for _ in range(10):
        await asyncio.sleep(0)
    open_while_held = sessions.open
    release.set()
    await asyncio.gather(*tasks)

    assert open_while_held == 2


@pytest.mark.usefixtures("restored_gate")
def test_installing_the_line_replaces_the_open_gate() -> None:
    use_strategy_gate(open_strategy_gate)

    install_strategy_line(_Sessions())

    assert strategy_gate() is not open_strategy_gate
