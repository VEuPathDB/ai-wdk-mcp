"""The two served research tools, capped to what a model reads.

A search answers with a ranked index. The leading results carry their text;
the rest carry the identity that reaches the full record again.
"""

from __future__ import annotations

from veupathdb_mcp.research.citations import (
    Citation,
    LiteratureFilters,
    LiteratureOutputOptions,
    LiteratureSort,
    LiteratureSource,
)
from veupathdb_mcp.research.literature.processing import (
    EnrichedPaper,
    LiteratureSearchResponse,
)
from veupathdb_mcp.research.literature.search import LiteratureSearchService
from veupathdb_mcp.research.models import (
    LiteratureSearchOut,
    PaperOut,
    SourceRef,
    WebResultOut,
    WebSearchOut,
)
from veupathdb_mcp.research.settings import get_research_settings
from veupathdb_mcp.research.text import truncate_text
from veupathdb_mcp.research.web.search import (
    WebSearchResponse,
    WebSearchResult,
    WebSearchService,
)

# A claim is grounded on the leading results, which keep their text. The rest
# are an index: enough to judge, and enough to ask for again.
LEADING_RESULTS = 3
LEADING_CHARS = 600
INDEXED_CHARS = 200

DEFAULT_OUTPUT_OPTIONS = LiteratureOutputOptions()
DEFAULT_FILTERS = LiteratureFilters()

_WEB_GUIDANCE = (
    "Ranked most relevant first. Only the first "
    f"{LEADING_RESULTS} carry the page text; the rest carry the url that "
    "holds it."
)
# A host prefixes the served tool names, so no guidance names a tool.
_LITERATURE_GUIDANCE = (
    "Ranked most relevant first. Only the first "
    f"{LEADING_RESULTS} carry the abstract. For a paper further down, search "
    "again for its title or its DOI with limit 1."
)


def _text_at(rank: int, *values: str | None) -> str:
    """The first value with text in it, cut to what this rank is worth."""
    limit = LEADING_CHARS if rank < LEADING_RESULTS else INDEXED_CHARS
    for value in values:
        cut = truncate_text(value, limit)
        if cut:
            return cut
    return ""


def _sources(citations: list[Citation]) -> list[SourceRef]:
    """One source per citation that names a url. A citation without one is skipped."""
    return [
        SourceRef(id=citation.id, url=citation.url, title=citation.title)
        for citation in citations
        if citation.url
    ]


def _web_result(rank: int, item: WebSearchResult) -> WebResultOut:
    return WebResultOut(
        title=item.title,
        url=item.url,
        snippet=_text_at(rank, item.summary, item.snippet),
    )


def _paper(rank: int, paper: EnrichedPaper) -> PaperOut:
    return PaperOut(
        title=paper.title,
        year=paper.year,
        journal=paper.journal_title,
        authors=paper.authors,
        doi=paper.doi,
        pmid=paper.pmid,
        url=paper.url,
        abstract=_text_at(rank, paper.abstract, paper.snippet),
    )


def _web_out(response: WebSearchResponse) -> WebSearchOut:
    return WebSearchOut(
        query=response.query,
        results=[_web_result(i, item) for i, item in enumerate(response.results)],
        sources=_sources(list(response.citations)),
        guidance=_WEB_GUIDANCE if response.results else "",
        error=response.error,
    )


def _literature_out(response: LiteratureSearchResponse) -> LiteratureSearchOut:
    return LiteratureSearchOut(
        query=response.query,
        results=[_paper(i, paper) for i, paper in enumerate(response.results)],
        sources=_sources(list(response.citations)),
        guidance=_LITERATURE_GUIDANCE if response.results else "",
    )


async def web_search(
    query: str,
    limit: int = 5,
    include_summary: bool = True,
    summary_max_chars: int = 600,
) -> WebSearchOut:
    """Search the open web and return ranked results with their sources.

    Args:
        query: Web search query.
        limit: Max number of results (1-10).
        include_summary: If true, fetch each result page to extract a short
            summary when the search engine's snippet is unhelpful.
        summary_max_chars: Max characters of per-result summary to include.
    """
    settings = get_research_settings()
    service = WebSearchService(timeout_seconds=settings.timeout_seconds)
    response = await service.search(
        query,
        limit=limit,
        include_summary=include_summary,
        summary_max_chars=summary_max_chars,
    )
    return _web_out(response)


async def literature_search(
    query: str,
    limit: int = 8,
    sort: LiteratureSort = "relevance",
    source: LiteratureSource = "all",
    output_options: LiteratureOutputOptions = DEFAULT_OUTPUT_OPTIONS,
    filters: LiteratureFilters = DEFAULT_FILTERS,
) -> LiteratureSearchOut:
    """Search scientific literature and return ranked papers with their sources.

    Args:
        query: Literature search query.
        limit: Max number of results (1-25).
        sort: Sort order: relevance (default) or newest.
        source: One literature API, or all of them together (default).
        output_options: Output formatting options.
        filters: Filters applied to the results after retrieval.
    """
    settings = get_research_settings()
    service = LiteratureSearchService(
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )
    response = await service.search(
        query,
        source=source,
        limit=limit,
        sort=sort,
        options=output_options,
        filters=filters,
    )
    return _literature_out(response)
