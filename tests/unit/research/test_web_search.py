"""A page is fetched for a summary only when the search engine's snippet is weak.

Fetching every page is slow and often refused, and a good snippet already
carries the text the summary would.
"""

from __future__ import annotations

import pytest
from ddgs.exceptions import DDGSException
from veupathdb.errors import ExternalServiceError

from veupathdb_mcp.research.web import search
from veupathdb_mcp.research.web.search import WebSearchService


async def test_only_fetches_summaries_for_weak_snippets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = WebSearchService()
    raw = [
        {
            "title": "Good",
            "href": "http://good",
            "body": "A nicely informative snippet, comfortably over the length threshold.",
        },
        {"title": "Weak", "href": "http://weak", "body": "short"},
    ]
    monkeypatch.setattr(
        WebSearchService, "_ddgs_text", staticmethod(lambda _q, _limit, _backend: raw)
    )
    fetched: list[str] = []

    async def fake_fetch(_client: object, url: str, *, max_chars: int) -> str:
        del max_chars
        fetched.append(url)
        return "enriched summary"

    monkeypatch.setattr(search, "fetch_page_summary", fake_fetch)

    resp = await svc.search("q", limit=5, include_summary=True)

    assert fetched == ["http://weak"]
    weak = next(r for r in resp.results if r.title == "Weak")
    good = next(r for r in resp.results if r.title == "Good")
    assert weak.snippet == "enriched summary"
    assert good.summary is None


RATELIMIT = "ratelimit 429"


def _answer(backend: str) -> list[dict[str, str]]:
    return [
        {
            "title": f"Answered by {backend}",
            "href": "http://answer",
            "body": "A nicely informative snippet, comfortably over the length threshold.",
        }
    ]


async def test_the_engine_that_answers_after_a_refusal_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = WebSearchService()
    refused, answered = search.TEXT_ENGINES[0], search.TEXT_ENGINES[1]
    asked: list[str] = []

    def one_refusal(_q: str, _limit: int, backend: str) -> list[dict[str, str]]:
        asked.append(backend)
        if backend == refused:
            raise DDGSException(RATELIMIT)
        return _answer(backend)

    monkeypatch.setattr(WebSearchService, "_ddgs_text", staticmethod(one_refusal))

    resp = await svc.search("plasmodium kinases", limit=5)
    diagnostics = resp.search_diagnostics

    assert asked == [refused, answered]
    assert diagnostics.backend == answered
    assert [
        (attempt.engine, attempt.results, attempt.error)
        for attempt in diagnostics.engines
    ] == [(refused, 0, RATELIMIT), (answered, 1, None)]
    assert [r.title for r in resp.results] == [f"Answered by {answered}"]


async def test_an_all_blocked_search_raises_with_every_engine_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def every_refusal(_q: str, _limit: int, backend: str) -> list[dict[str, str]]:
        detail = f"{backend} refused"
        raise DDGSException(detail)

    monkeypatch.setattr(WebSearchService, "_ddgs_text", staticmethod(every_refusal))

    with pytest.raises(ExternalServiceError) as refusal:
        await WebSearchService().search("plasmodium kinases", limit=5)

    message = str(refusal.value)
    assert [engine for engine in search.TEXT_ENGINES if engine not in message] == []
    assert "refused" in message
