"""Crossref routes a request that names a mailbox to its polite pool."""

from __future__ import annotations

from types import TracebackType
from typing import ClassVar

import pytest
from pydantic import JsonValue

from veupathdb_mcp.research.literature.clients import crossref
from veupathdb_mcp.research.literature.clients.crossref import CrossrefClient

MAILBOX = "help@veupathdb.org"


class _StubResponse:
    """The empty Crossref answer, which the client parses into no items."""

    @staticmethod
    def raise_for_status() -> None:
        return

    @staticmethod
    def json() -> JsonValue:
        return {"message": {"items": []}}


class _RecordingClient:
    """Stands in for ``httpx.AsyncClient`` and keeps the headers it was built with."""

    recorded: ClassVar[list[dict[str, str]]] = []

    def __init__(self, *, timeout: float, headers: dict[str, str]) -> None:
        del timeout
        _RecordingClient.recorded.append(headers)

    async def __aenter__(self) -> "_RecordingClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False

    async def get(
        self,
        url: str,
        params: dict[str, str],
        follow_redirects: bool,
    ) -> _StubResponse:
        del url, params, follow_redirects
        return _StubResponse()


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    _RecordingClient.recorded = []
    monkeypatch.setattr(crossref.httpx, "AsyncClient", _RecordingClient)
    return _RecordingClient.recorded


async def test_a_configured_mailbox_reaches_crossref(
    monkeypatch: pytest.MonkeyPatch,
    recorded: list[dict[str, str]],
) -> None:
    monkeypatch.setenv("RESEARCH_MCP_CROSSREF_MAILTO", MAILBOX)

    await CrossrefClient().search("kinase", limit=2, abstract_max_chars=200)

    assert recorded == [
        {"User-Agent": f"veupathdb-research-mcp/1.0 (mailto:{MAILBOX})"}
    ]


async def test_without_a_mailbox_the_call_names_none(
    recorded: list[dict[str, str]],
) -> None:
    """An invented address buys nothing; the anonymous pool is the honest default."""
    await CrossrefClient().search("kinase", limit=2, abstract_max_chars=200)

    assert recorded == [{"User-Agent": "veupathdb-research-mcp/1.0"}]
