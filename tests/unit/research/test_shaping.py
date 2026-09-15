"""The served result is a ranked index: the leading rows carry the text."""

from __future__ import annotations

import pytest

from veupathdb_mcp.research import tools
from veupathdb_mcp.research.citations import Citation
from veupathdb_mcp.research.literature.processing import (
    EnrichedPaper,
    LiteratureSearchResponse,
)
from veupathdb_mcp.research.literature.search import LiteratureSearchService
from veupathdb_mcp.research.models import (
    EngineAttempt,
    SearchDiagnostics,
    SourceStatus,
)
from veupathdb_mcp.research.web.search import (
    WebSearchResponse,
    WebSearchResult,
    WebSearchService,
)

LONG = "x" * 4000


ANSWERED = SearchDiagnostics(
    backend="mojeek",
    engines=[
        EngineAttempt(engine="duckduckgo", error="ratelimit 429"),
        EngineAttempt(engine="mojeek", results=5),
    ],
)


def _web_response(count: int) -> WebSearchResponse:
    return WebSearchResponse(
        query="plasmodium kinases",
        effective_query="plasmodium kinases",
        search_adjusted=False,
        search_diagnostics=ANSWERED,
        results=[
            WebSearchResult(
                title=f"Result {i}",
                url=f"https://example.org/{i}",
                snippet=LONG,
            )
            for i in range(count)
        ],
        citations=[
            Citation(
                id=f"web_{i}",
                source="web",
                title=f"Result {i}",
                url=f"https://example.org/{i}",
            )
            for i in range(count)
        ],
    )


def _literature_response(
    count: int, statuses: list[SourceStatus] | None = None
) -> LiteratureSearchResponse:
    return LiteratureSearchResponse(
        query="plasmodium kinome",
        source="all",
        sort="relevance",
        include_abstract=True,
        abstract_max_chars=2000,
        max_authors=5,
        filters=tools.DEFAULT_FILTERS,
        results=[
            EnrichedPaper(
                title=f"Paper {i}",
                doi=f"10.1/{i}",
                url=f"https://doi.org/10.1/{i}",
                abstract=LONG,
                source="europepmc",
            )
            for i in range(count)
        ],
        citations=[
            Citation(
                id=f"epmc_{i}",
                source="europepmc",
                title=f"Paper {i}",
                url=f"https://doi.org/10.1/{i}",
            )
            for i in range(count)
        ],
        sources_status=statuses
        if statuses is not None
        else [SourceStatus(source="europepmc", results=count)],
    )


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _web(
        _self: WebSearchService,
        query: str,
        limit: int = 5,
        *,
        include_summary: bool = False,
        summary_max_chars: int = 600,
    ) -> WebSearchResponse:
        del query, include_summary, summary_max_chars
        return _web_response(limit)

    async def _literature(
        _self: LiteratureSearchService,
        query: str,
        **kwargs: object,
    ) -> LiteratureSearchResponse:
        del query
        limit = kwargs["limit"]
        assert isinstance(limit, int)
        return _literature_response(limit)

    monkeypatch.setattr(WebSearchService, "search", _web)
    monkeypatch.setattr(LiteratureSearchService, "search", _literature)


async def test_web_search_gives_only_the_leading_results_their_full_text(
    stubbed: None,
) -> None:
    del stubbed

    out = await tools.web_search("plasmodium kinases", limit=5)

    lengths = [len(result.snippet) for result in out.results]
    assert lengths == [tools.LEADING_CHARS] * 3 + [tools.INDEXED_CHARS] * 2


async def test_web_search_keeps_every_result_reachable_by_url(stubbed: None) -> None:
    del stubbed

    out = await tools.web_search("plasmodium kinases", limit=5)

    assert [result.url for result in out.results] == [
        f"https://example.org/{i}" for i in range(5)
    ]
    assert out.guidance != ""


async def test_web_search_carries_one_source_per_citation(stubbed: None) -> None:
    del stubbed

    out = await tools.web_search("plasmodium kinases", limit=4)

    assert [source.url for source in out.sources] == [
        f"https://example.org/{i}" for i in range(4)
    ]
    assert [source.id for source in out.sources] == [f"web_{i}" for i in range(4)]


async def test_literature_search_gives_only_the_leading_papers_their_abstract(
    stubbed: None,
) -> None:
    del stubbed

    out = await tools.literature_search("plasmodium kinome", limit=8)

    lengths = [len(paper.abstract) for paper in out.results]
    assert lengths == [tools.LEADING_CHARS] * 3 + [tools.INDEXED_CHARS] * 5


async def test_literature_search_names_the_handle_for_the_full_record(
    stubbed: None,
) -> None:
    del stubbed

    out = await tools.literature_search("plasmodium kinome", limit=8)

    assert all(paper.doi for paper in out.results)
    assert "DOI" in out.guidance
    assert len(out.sources) == 8


async def test_no_guidance_names_a_tool(stubbed: None) -> None:
    """A host prefixes the served names, so guidance that names one is wrong."""
    del stubbed

    web = await tools.web_search("plasmodium kinases", limit=5)
    literature = await tools.literature_search("plasmodium kinome", limit=8)

    named = [
        name
        for name in ("web_search", "literature_search")
        for guidance in (web.guidance, literature.guidance)
        if name in guidance
    ]
    assert named == []


async def test_a_web_search_without_a_query_reports_why_and_offers_no_guidance() -> (
    None
):
    out = await tools.web_search("   ")

    assert (out.error, out.guidance, out.results) == ("query_required", "", [])


async def test_a_web_search_names_the_engine_that_answered(stubbed: None) -> None:
    del stubbed

    out = await tools.web_search("plasmodium kinases", limit=5)

    assert out.search_diagnostics.backend == "mojeek"
    assert [
        (attempt.engine, attempt.error) for attempt in out.search_diagnostics.engines
    ] == [("duckduckgo", "ratelimit 429"), ("mojeek", None)]


async def test_a_literature_search_reports_what_each_source_did(
    stubbed: None,
) -> None:
    del stubbed

    out = await tools.literature_search("plasmodium kinome", limit=8)

    assert [
        (status.source, status.results, status.error) for status in out.sources_status
    ] == [("europepmc", 8, None)]


async def test_guidance_says_when_the_indexed_sources_returned_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Europe PMC and PubMed match every term, so a long query reaches neither."""
    statuses = [
        SourceStatus(source="europepmc", results=0),
        SourceStatus(source="pubmed", results=0),
        SourceStatus(source="crossref", results=8),
        SourceStatus(source="openalex", results=8),
    ]

    async def _quiet(
        _self: LiteratureSearchService,
        query: str,
        **kwargs: object,
    ) -> LiteratureSearchResponse:
        del query, kwargs
        return _literature_response(8, statuses)

    monkeypatch.setattr(LiteratureSearchService, "search", _quiet)

    out = await tools.literature_search(
        "PF3D7_0304600 circumsporozoite protein expression life cycle transcript"
    )

    assert "Europe PMC and PubMed returned nothing" in out.guidance
    assert "shorter query" in out.guidance
    assert "did not answer" not in out.guidance


async def test_guidance_names_a_source_that_did_not_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = [
        SourceStatus(source="europepmc", results=0, error="read timeout"),
        SourceStatus(source="pubmed", results=0, error="429"),
        SourceStatus(source="crossref", results=2),
    ]

    async def _partial(
        _self: LiteratureSearchService,
        query: str,
        **kwargs: object,
    ) -> LiteratureSearchResponse:
        del query, kwargs
        return _literature_response(2, statuses)

    monkeypatch.setattr(LiteratureSearchService, "search", _partial)

    out = await tools.literature_search("plasmodium kinome", limit=2)

    assert "europepmc, pubmed" in out.guidance
    assert "crossref" not in out.guidance
    assert "source" in out.guidance
