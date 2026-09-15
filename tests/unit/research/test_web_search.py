"""A page is fetched for a summary only when the search engine's snippet is weak.

Fetching every page is slow and often refused, and a good snippet already
carries the text the summary would.
"""

from __future__ import annotations

from decimal import Decimal

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


BRAVE_ROWS = [
    {
        "title": "Circumsporozoite protein - Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Circumsporozoite_protein",
        "description": "The circumsporozoite protein is the major surface antigen of the sporozoite.",
    }
]
PRICE = Decimal("0.005")
SERVICE = "web search"


def _keyed(monkeypatch: pytest.MonkeyPatch) -> tuple[WebSearchService, list[str]]:
    """A service with a Brave key, whose scraped engines record when they are asked."""
    asked: list[str] = []

    def scraped(_q: str, _limit: int, backend: str) -> list[dict[str, str]]:
        asked.append(backend)
        return _answer(backend)

    monkeypatch.setattr(WebSearchService, "_ddgs_text", staticmethod(scraped))
    return WebSearchService(brave_api_key="k", brave_cost_usd=PRICE), asked


async def test_a_keyed_search_asks_brave_first_and_carries_its_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, asked = _keyed(monkeypatch)

    async def brave(
        _self: WebSearchService, _q: str, _limit: int
    ) -> list[dict[str, str]]:
        return BRAVE_ROWS

    monkeypatch.setattr(WebSearchService, "_brave_rows", brave)

    resp = await svc.search("circumsporozoite protein", limit=5)

    assert asked == []
    assert resp.search_diagnostics.backend == search.BRAVE_API
    assert [
        (attempt.engine, attempt.results, attempt.error)
        for attempt in resp.search_diagnostics.engines
    ] == [(search.BRAVE_API, 1, None)]
    assert [(r.title, r.url, r.snippet) for r in resp.results] == [
        (
            "Circumsporozoite protein - Wikipedia",
            "https://en.wikipedia.org/wiki/Circumsporozoite_protein",
            "The circumsporozoite protein is the major surface antigen of the sporozoite.",
        )
    ]
    assert resp.cost_usd == PRICE


async def test_a_refused_brave_search_falls_back_to_the_scraped_engines_at_no_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, asked = _keyed(monkeypatch)

    async def refused(
        _self: WebSearchService, _q: str, _limit: int
    ) -> list[dict[str, str]]:
        refusal = ExternalServiceError(SERVICE, "brave-api 429 Too Many Requests")
        raise refusal

    monkeypatch.setattr(WebSearchService, "_brave_rows", refused)

    resp = await svc.search("plasmodium kinases", limit=5)

    assert asked == [search.TEXT_ENGINES[0]]
    assert resp.search_diagnostics.backend == search.TEXT_ENGINES[0]
    assert [
        (attempt.engine, attempt.results) for attempt in resp.search_diagnostics.engines
    ] == [(search.BRAVE_API, 0), (search.TEXT_ENGINES[0], 1)]
    assert "429" in (resp.search_diagnostics.engines[0].error or "")
    assert resp.cost_usd == Decimal(0)


async def test_without_a_key_brave_is_not_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        WebSearchService,
        "_ddgs_text",
        staticmethod(lambda _q, _limit, backend: _answer(backend)),
    )

    resp = await WebSearchService().search("plasmodium kinases", limit=5)

    assert [attempt.engine for attempt in resp.search_diagnostics.engines] == [
        search.TEXT_ENGINES[0]
    ]
    assert resp.cost_usd == Decimal(0)


NO_RESULTS = "No results found."


async def test_an_engine_that_finds_nothing_answered_and_the_next_one_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ddgs reports an empty answer as an exception; it is not a refusal."""
    empty, answered = search.TEXT_ENGINES[0], search.TEXT_ENGINES[1]

    def one_empty(_q: str, _limit: int, backend: str) -> list[dict[str, str]]:
        if backend == empty:
            raise DDGSException(NO_RESULTS)
        return _answer(backend)

    monkeypatch.setattr(WebSearchService, "_ddgs_text", staticmethod(one_empty))

    resp = await WebSearchService().search("plasmodium kinases", limit=5)

    assert [
        (attempt.engine, attempt.results, attempt.error)
        for attempt in resp.search_diagnostics.engines
    ] == [(empty, 0, None), (answered, 1, None)]


async def test_a_query_no_engine_finds_a_page_for_answers_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def every_empty(_q: str, _limit: int, _backend: str) -> list[dict[str, str]]:
        raise DDGSException(NO_RESULTS)

    monkeypatch.setattr(WebSearchService, "_ddgs_text", staticmethod(every_empty))

    resp = await WebSearchService().search("site:plasmodb.org 3D7 gene count", limit=5)

    assert resp.results == []
    assert resp.error is None
    assert resp.search_diagnostics.backend == ""
    assert [attempt.error for attempt in resp.search_diagnostics.engines] == [
        None
    ] * len(search.TEXT_ENGINES)
