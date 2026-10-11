"""Text shaping and page summary extraction hold for every value they accept."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from veupathdb_mcp.research import text
from veupathdb_mcp.research.text import (
    fetch_page_summary,
    limit_authors,
    norm_for_match,
    truncate_text,
)

_REFUSED = "the url names no host"

_ADDRESSES = {
    "example.org": ["93.184.215.14"],
    "papers.example.org": ["93.184.215.15"],
    "intranet.example.org": ["10.0.0.5"],
    "metadata.example.org": ["169.254.169.254"],
}

_PAGE = (
    '<html><head><meta name="description" content="A kinase atlas of '
    'Plasmodium falciparum gametocytes."></head><body></body></html>'
)


@pytest.fixture(autouse=True)
def _known_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _resolve(host: str, port: int) -> list[str]:
        del port
        return _ADDRESSES[host]

    monkeypatch.setattr(text, "_addresses", _resolve)


def _serving(
    pages: dict[str, httpx.Response], asked: list[str], *, follows: bool = False
) -> httpx.AsyncClient:
    def _handle(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return pages[str(request.url)]

    return httpx.AsyncClient(
        transport=httpx.MockTransport(_handle), follow_redirects=follows
    )


class _RefusingClient:
    """Stands in for ``httpx.AsyncClient``; every stream is refused outright."""

    @asynccontextmanager
    async def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[None]:
        del args, kwargs
        raise httpx.InvalidURL(_REFUSED)
        yield


def test_missing_text_truncates_to_nothing() -> None:
    assert (truncate_text(None, 10), truncate_text("   ", 10)) == (None, None)


def test_truncated_text_stays_within_its_budget() -> None:
    cut = truncate_text("word " * 100, 20)

    assert cut is not None
    assert (len(cut), cut.endswith("...")) == (20, True)


def test_missing_text_normalizes_to_the_empty_string() -> None:
    assert (norm_for_match(None), norm_for_match("  A  B ")) == ("", "a b")


def test_missing_authors_limit_to_nothing() -> None:
    assert (limit_authors(None, 5), limit_authors([" "], 5)) == (None, None)


async def test_a_page_that_cannot_be_read_carries_no_summary() -> None:
    """One unreadable page must not end the search that asked for it."""
    summary = await fetch_page_summary(
        _RefusingClient(), "https://example.org/x", max_chars=100
    )

    assert summary is None


async def test_a_result_without_a_url_is_never_fetched() -> None:
    assert await fetch_page_summary(_RefusingClient(), None, max_chars=100) is None


async def test_a_public_page_after_a_public_redirect_is_summarized() -> None:
    asked: list[str] = []
    client = _serving(
        {
            "https://example.org/x": httpx.Response(
                302, headers={"location": "https://papers.example.org/atlas"}
            ),
            "https://papers.example.org/atlas": httpx.Response(200, text=_PAGE),
        },
        asked,
    )

    summary = await fetch_page_summary(client, "https://example.org/x", max_chars=200)

    assert summary == "A kinase atlas of Plasmodium falciparum gametocytes."
    assert asked == ["https://example.org/x", "https://papers.example.org/atlas"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/v1/me",
        "http://[::1]/",
        "http://intranet.example.org/",
        "http://metadata.example.org/latest/meta-data/",
        "file:///etc/passwd",
    ],
)
async def test_an_address_inside_the_network_is_never_fetched(url: str) -> None:
    asked: list[str] = []

    summary = await fetch_page_summary(_serving({}, asked), url, max_chars=200)

    assert (summary, asked) == (None, [])


@pytest.mark.parametrize("follows", [False, True])
async def test_a_redirect_into_the_network_is_not_followed(follows: bool) -> None:
    asked: list[str] = []
    client = _serving(
        {
            "https://example.org/x": httpx.Response(
                302, headers={"location": "http://intranet.example.org/admin"}
            ),
            "http://intranet.example.org/admin": httpx.Response(200, text=_PAGE),
        },
        asked,
        follows=follows,
    )

    summary = await fetch_page_summary(client, "https://example.org/x", max_chars=200)

    assert (summary, asked) == (None, ["https://example.org/x"])
