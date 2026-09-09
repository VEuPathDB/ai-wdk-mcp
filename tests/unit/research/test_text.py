"""Text shaping and page summary extraction hold for every value they accept."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from veupathdb_mcp.research.text import (
    fetch_page_summary,
    limit_authors,
    norm_for_match,
    truncate_text,
)

_REFUSED = "the url names no host"


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
