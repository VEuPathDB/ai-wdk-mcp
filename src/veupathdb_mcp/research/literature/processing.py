"""Deduplication, filtering, ranking, and response assembly for literature search."""

from dataclasses import dataclass

from pydantic import Field
from veupathdb.model import CamelModel

from veupathdb_mcp.research.citations import (
    Citation,
    LiteratureFilters,
    LiteratureOutputOptions,
    LiteratureSort,
    LiteratureSource,
    ensure_unique_citation_tags,
)
from veupathdb_mcp.research.literature.papers import ParsedPaper
from veupathdb_mcp.research.text import (
    LiteratureItemContext,
    dedupe_key,
    limit_authors,
    passes_filters,
    rerank_score,
    truncate_text,
)


class SourcePayload(CamelModel):
    """Typed model for parsing a source's response payload."""

    results: list[ParsedPaper] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    error: str | None = None


class EnrichedPaper(ParsedPaper):
    """ParsedPaper enriched with source tracking and optional reranking score."""

    source: str = ""
    score: float | None = None
    score_parts: dict[str, float] | None = None


class LiteratureSearchResponse(CamelModel):
    """Final response from the literature search service."""

    query: str
    source: LiteratureSource
    sort: LiteratureSort
    include_abstract: bool
    abstract_max_chars: int
    max_authors: int
    filters: LiteratureFilters
    results: list[EnrichedPaper]
    citations: list[Citation]


@dataclass
class LiteratureResultData:
    """Aggregated result data for response assembly."""

    results: list[EnrichedPaper]
    citations_by_key: dict[str, Citation]
    by_source: dict[str, SourcePayload]
    limit: int


def deduplicate_and_filter(
    *,
    by_source: dict[str, SourcePayload],
    options: LiteratureOutputOptions,
    filters: LiteratureFilters,
) -> tuple[list[EnrichedPaper], dict[str, Citation]]:
    """Merge, filter, and deduplicate results from all sources."""
    filtered: list[EnrichedPaper] = []
    citations_by_key: dict[str, Citation] = {}
    index_by_key: dict[str, int] = {}

    for src, payload in by_source.items():
        for i, paper in enumerate(payload.results):
            c = payload.citations[i] if i < len(payload.citations) else None

            item_ctx = LiteratureItemContext(
                title=paper.title,
                authors=paper.authors or None,
                year=paper.year,
                doi=paper.doi,
                pmid=paper.pmid,
                journal=paper.journal_title,
            )
            if not passes_filters(item_ctx, filters):
                continue

            key = dedupe_key(paper)
            existing_index = index_by_key.get(key)
            if existing_index is not None:
                # The same paper from another source can supply a missing abstract.
                kept = filtered[existing_index]
                if not (kept.abstract or "").strip() and (paper.abstract or "").strip():
                    merged = (
                        truncate_text(paper.abstract, options.abstract_max_chars)
                        if options.include_abstract
                        else paper.abstract
                    )
                    filtered[existing_index] = kept.model_copy(
                        update={"abstract": merged}
                    )
                continue

            authors_limited = limit_authors(
                paper.authors or None,
                options.max_authors,
            )
            abstract_value = (
                truncate_text(paper.abstract, options.abstract_max_chars)
                if options.include_abstract
                else paper.abstract
            )
            filtered.append(
                EnrichedPaper(
                    **paper.model_dump(exclude={"authors", "abstract"}),
                    source=src,
                    authors=authors_limited or [],
                    abstract=abstract_value,
                )
            )
            index_by_key[key] = len(filtered) - 1

            if c is not None:
                citation_authors = limit_authors(c.authors, options.max_authors)
                citations_by_key[key] = c.model_copy(
                    update={"authors": citation_authors},
                )

    return filtered, citations_by_key


def sort_results(
    results: list[EnrichedPaper],
    *,
    sort: LiteratureSort,
    source: LiteratureSource,
    query: str,
) -> list[EnrichedPaper]:
    """Sort (and optionally rerank) the filtered results."""
    if results and sort == "newest":
        return sorted(
            results,
            key=lambda r: (r.year is not None, r.year or 0),
            reverse=True,
        )

    if results and sort == "relevance" and source == "all":
        scored = [
            r.model_copy(
                update={"score": round(score, 2), "score_parts": parts},
            )
            for r in results
            for score, parts in [rerank_score(query, r)]
        ]
        return sorted(
            scored,
            key=lambda r: (r.score is not None, r.score or 0.0),
            reverse=True,
        )

    return results


def build_response(
    *,
    query: str,
    source: LiteratureSource,
    sort: LiteratureSort,
    options: LiteratureOutputOptions,
    filters: LiteratureFilters,
    result_data: LiteratureResultData,
) -> LiteratureSearchResponse:
    """Assemble the final response payload."""
    sliced = result_data.results[: result_data.limit]

    citations: list[Citation] = []
    for r in sliced:
        c = result_data.citations_by_key.get(dedupe_key(r))
        if c is not None:
            citations.append(c)

    ensure_unique_citation_tags(citations)

    return LiteratureSearchResponse(
        query=query,
        source=source,
        sort=sort,
        include_abstract=options.include_abstract,
        abstract_max_chars=options.abstract_max_chars,
        max_authors=options.max_authors,
        filters=filters,
        results=sliced,
        citations=citations,
    )
