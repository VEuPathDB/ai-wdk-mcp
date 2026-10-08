"""A page is fetched for a summary only when the search engine's snippet is weak.

Fetching every page is slow and often refused, and a good snippet already
carries the text the summary would.
"""

from __future__ import annotations

import inspect

import ddgs.ddgs
import httpx
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


SERVICE = "web search"
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


SEARXNG_ROWS = [
    {
        "title": "Circumsporozoite protein - Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Circumsporozoite_protein",
        "content": "The circumsporozoite protein is the major surface antigen of the sporozoite.",
        "engines": ["google cse"],
    }
]


def _metasearch(monkeypatch: pytest.MonkeyPatch) -> tuple[WebSearchService, list[str]]:
    """A service with a SearXNG url, whose scraped engines record when they are asked."""
    asked: list[str] = []

    def scraped(_q: str, _limit: int, backend: str) -> list[dict[str, str]]:
        asked.append(backend)
        return _answer(backend)

    monkeypatch.setattr(WebSearchService, "_ddgs_text", staticmethod(scraped))
    return WebSearchService(searxng_url="http://searxng:8080"), asked


async def test_the_metasearch_answers_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, asked = _metasearch(monkeypatch)

    async def rows(
        _self: WebSearchService, _q: str, _limit: int
    ) -> list[dict[str, object]]:
        return SEARXNG_ROWS

    monkeypatch.setattr(WebSearchService, "_searxng_rows", rows)

    resp = await svc.search("circumsporozoite protein", limit=5)

    assert asked == []
    assert resp.search_diagnostics.backend == search.SEARXNG
    assert [
        (attempt.engine, attempt.results, attempt.error)
        for attempt in resp.search_diagnostics.engines
    ] == [(search.SEARXNG, 1, None)]
    assert [(r.title, r.url, r.snippet) for r in resp.results] == [
        (
            "Circumsporozoite protein - Wikipedia",
            "https://en.wikipedia.org/wiki/Circumsporozoite_protein",
            "The circumsporozoite protein is the major surface antigen of the sporozoite.",
        )
    ]


async def test_a_metasearch_that_finds_nothing_answered_and_the_scraped_engines_follow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, asked = _metasearch(monkeypatch)

    async def nothing(
        _self: WebSearchService, _q: str, _limit: int
    ) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(WebSearchService, "_searxng_rows", nothing)

    resp = await svc.search("plasmodium kinases", limit=5)

    assert asked == [search.TEXT_ENGINES[0]]
    assert [
        (attempt.engine, attempt.results, attempt.error)
        for attempt in resp.search_diagnostics.engines
    ] == [(search.SEARXNG, 0, None), (search.TEXT_ENGINES[0], 1, None)]


async def test_a_metasearch_that_is_down_is_a_refused_attempt_not_a_dead_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, asked = _metasearch(monkeypatch)

    async def down(
        _self: WebSearchService, _q: str, _limit: int
    ) -> list[dict[str, object]]:
        refusal = ExternalServiceError(SERVICE, "searxng connection refused")
        raise refusal

    monkeypatch.setattr(WebSearchService, "_searxng_rows", down)

    resp = await svc.search("plasmodium kinases", limit=5)

    assert asked == [search.TEXT_ENGINES[0]]
    assert "searxng connection refused" in (
        resp.search_diagnostics.engines[0].error or ""
    )


def _served(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    """Answer every request the search module makes with one response."""
    built = httpx.AsyncClient

    def factory(*, timeout: float) -> httpx.AsyncClient:
        return built(
            timeout=timeout,
            transport=httpx.MockTransport(lambda _request: response),
        )

    monkeypatch.setattr(search.httpx, "AsyncClient", factory)


HTML_BODY = "<html><body>Access to this instance is blocked.</body></html>"


async def test_a_metasearch_that_answers_html_is_a_refused_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, asked = _metasearch(monkeypatch)
    _served(monkeypatch, httpx.Response(200, text=HTML_BODY))

    resp = await svc.search("plasmodium kinases", limit=5)

    assert asked == [search.TEXT_ENGINES[0]]
    assert resp.search_diagnostics.backend == search.TEXT_ENGINES[0]
    attempt = resp.search_diagnostics.engines[0]
    assert attempt.engine == search.SEARXNG
    assert attempt.results == 0
    assert "searxng 200" in (attempt.error or "")
    assert [r.title for r in resp.results] == [f"Answered by {search.TEXT_ENGINES[0]}"]


async def test_a_metasearch_that_answers_another_shape_is_a_refused_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, asked = _metasearch(monkeypatch)
    _served(monkeypatch, httpx.Response(200, json=["not", "an", "envelope"]))

    resp = await svc.search("plasmodium kinases", limit=5)

    assert asked == [search.TEXT_ENGINES[0]]
    assert resp.search_diagnostics.engines[0].error is not None
    assert [r.title for r in resp.results] == [f"Answered by {search.TEXT_ENGINES[0]}"]


async def test_the_metasearch_and_then_the_scraped_engines_are_every_engine_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = WebSearchService(searxng_url="http://searxng:8080")
    asked: list[str] = []

    async def nothing(
        _self: WebSearchService, _q: str, _limit: int
    ) -> list[dict[str, object]]:
        asked.append(search.SEARXNG)
        return []

    def empty(_q: str, _limit: int, backend: str) -> list[dict[str, str]]:
        asked.append(backend)
        raise DDGSException(NO_RESULTS)

    monkeypatch.setattr(WebSearchService, "_searxng_rows", nothing)
    monkeypatch.setattr(WebSearchService, "_ddgs_text", staticmethod(empty))

    resp = await svc.search("plasmodium kinases", limit=5)

    assert asked == [search.SEARXNG, *search.TEXT_ENGINES]
    assert resp.results == []


def test_a_web_search_answer_carries_no_price() -> None:
    assert set(search.WebSearchResponse.model_fields) == {
        "query",
        "effective_query",
        "search_adjusted",
        "search_diagnostics",
        "results",
        "citations",
        "error",
    }


def test_the_empty_answer_ddgs_reports_is_the_literal_this_module_reads() -> None:
    """The empty-result signal is a string ddgs builds; pin it against ddgs."""
    assert f'"{search._NO_RESULTS}"' in inspect.getsource(ddgs.ddgs.DDGS)


def test_no_engine_is_brave() -> None:
    """The scraped fallback asks no Brave engine."""
    assert "brave" not in search.TEXT_ENGINES
