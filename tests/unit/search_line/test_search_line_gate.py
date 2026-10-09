from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from veupathdb import MetricAttrs, get_observer, set_observer
from veupathdb.wdk import SearchRequest, VEuPathDBClient

from veupathdb_mcp.search_line import search_line_gate, told_while_waiting
from veupathdb_mcp.server import SearchTurnPerCall


def _request(*names: str, site_id: str = "plasmodb") -> SearchRequest:
    return SearchRequest(site_id=site_id, kind="report", search_names=frozenset(names))


class _HeldLine:
    def __init__(self) -> None:
        self.free = asyncio.Event()
        self.waiting = asyncio.Event()
        self.held: list[str] = []

    @asynccontextmanager
    async def hold(self, site_id: str) -> AsyncIterator[None]:
        self.waiting.set()
        await self.free.wait()
        self.held.append(site_id)
        yield


class _Waits:
    def __init__(self) -> None:
        self.waits: list[MetricAttrs] = []

    def on_wdk_request(self, _seconds: float, _attrs: MetricAttrs, /) -> None:
        return None

    def on_wdk_retry(self, _attrs: MetricAttrs, /) -> None:
        return None

    def on_site_search_request(self, _seconds: float, _attrs: MetricAttrs, /) -> None:
        return None

    def on_site_search_retry(self, _attrs: MetricAttrs, /) -> None:
        return None

    def on_wdk_search_wait(self, _seconds: float, attrs: MetricAttrs, /) -> None:
        self.waits.append(attrs)


class _Listener:
    def __init__(self) -> None:
        self.told: list[str] = []
        self.said = asyncio.Event()

    async def waiting(self, site_id: str) -> None:
        self.told.append(f"waiting:{site_id}")
        self.said.set()

    async def running(self, site_id: str) -> None:
        self.told.append(f"running:{site_id}")


@pytest.fixture
def waits() -> Iterator[_Waits]:
    recording = _Waits()
    previous = get_observer()
    set_observer(recording)
    try:
        yield recording
    finally:
        set_observer(previous)


async def test_a_cheap_search_passes_without_the_line() -> None:
    line = _HeldLine()

    async with search_line_gate(line)(_request("GenesByText")):
        pass

    assert line.waiting.is_set() is False


async def test_a_high_speed_snp_search_waits_for_the_line_and_reports_the_wait(
    waits: _Waits,
) -> None:
    line = _HeldLine()

    async def search() -> None:
        async with search_line_gate(line)(_request("NgsSnpsByLocation")):
            pass

    running = asyncio.create_task(search())
    await line.waiting.wait()
    assert running.done() is False
    line.free.set()
    await running

    assert line.held == ["plasmodb"]
    assert waits.waits == [{"site": "plasmodb", "line": "expensive"}]


async def test_the_host_names_what_else_is_expensive() -> None:
    line = _HeldLine()
    line.free.set()

    async with search_line_gate(line, lambda r: "GenesByText" in r.search_names)(
        _request("GenesByText")
    ):
        pass

    assert line.held == ["plasmodb"]


async def test_a_long_wait_is_told_and_then_its_end() -> None:
    line = _HeldLine()
    listener = _Listener()

    async def search() -> None:
        with told_while_waiting(listener):
            async with search_line_gate(line, notice_seconds=0.0)(
                _request("GenesByNgsSnps")
            ):
                pass

    running = asyncio.create_task(search())
    await listener.said.wait()
    line.free.set()
    await running

    assert listener.told == ["waiting:plasmodb", "running:plasmodb"]


async def test_a_short_wait_tells_nothing() -> None:
    line = _HeldLine()
    line.free.set()
    listener = _Listener()

    with told_while_waiting(listener):
        async with search_line_gate(line)(_request("GenesByNgsSnps")):
            pass

    assert listener.told == []


class _Load(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.in_flight = 0
        self.most_in_flight = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        del request
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        for _ in range(5):
            await asyncio.sleep(0)
        self.in_flight -= 1
        return httpx.Response(200, json={"id": 1})


async def test_one_served_call_sends_one_search_per_site_at_a_time() -> None:
    load = _Load()
    client = VEuPathDBClient(
        base_url="https://plasmodb.invalid/service", site_id="plasmodb"
    )
    async with client._client_lock:
        client._client = httpx.AsyncClient(base_url=client.base_url, transport=load)
    report = "/record-types/transcript/searches/GenesByText/reports/standard"

    async def the_tool(context: Any) -> Any:
        del context
        return await asyncio.gather(
            client.post(report, json={}), client.post(report, json={})
        )

    context: Any = None
    await SearchTurnPerCall().on_call_tool(context, the_tool)

    assert load.most_in_flight == 1
