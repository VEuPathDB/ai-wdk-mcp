"""Aggregation keeps every source honest: content survives, one failure does not spread."""

from __future__ import annotations

import pytest
from veupathdb.errors import ExternalServiceError

from veupathdb_mcp.research.citations import (
    LiteratureFilters,
    LiteratureOutputOptions,
)
from veupathdb_mcp.research.literature.clients._base import SearchResponse
from veupathdb_mcp.research.literature.papers import ParsedPaper
from veupathdb_mcp.research.literature.processing import (
    SourcePayload,
    deduplicate_and_filter,
)
from veupathdb_mcp.research.literature.search import LiteratureSearchService
from veupathdb_mcp.research.text import rerank_score


def test_dedup_keeps_abstract_from_a_later_source() -> None:
    crossref = ParsedPaper(
        title="Blood-stage vaccine antigens", doi="10.1/x", snippet="Vaccine"
    )
    s2 = ParsedPaper(
        title="Blood-stage vaccine antigens",
        doi="10.1/x",
        abstract="Criteria: surface localization, immune epitopes, positive selection.",
    )
    by_source = {
        "crossref": SourcePayload(results=[crossref]),
        "semanticscholar": SourcePayload(results=[s2]),
    }
    filtered, _ = deduplicate_and_filter(
        by_source=by_source,
        options=LiteratureOutputOptions(
            include_abstract=True, abstract_max_chars=2000, max_authors=2
        ),
        filters=LiteratureFilters(),
    )
    assert len(filtered) == 1
    assert filtered[0].abstract is not None
    assert "surface localization" in filtered[0].abstract


def test_rerank_does_not_inflate_a_missing_abstract() -> None:
    paper = ParsedPaper(
        title="Old DNA molecules", journal_title="Vaccine", snippet="Vaccine"
    )
    query = "criteria for selecting Plasmodium falciparum blood-stage vaccine antigens"
    _score, parts = rerank_score(query, paper)
    assert parts["abstract"] == 0.0


async def test_one_source_failure_does_not_kill_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = LiteratureSearchService()

    async def fail(*_a: object, **_k: object) -> SearchResponse:
        service, detail = "Semantic Scholar", "500"
        raise ExternalServiceError(service, detail)

    async def good(*_a: object, **_k: object) -> SearchResponse:
        return SearchResponse(
            query="vaccine antigens",
            source="europepmc",
            results=[
                ParsedPaper(
                    title="Good paper",
                    doi="10.1/g",
                    abstract="A real abstract, long enough to count as genuine content.",
                )
            ],
            citations=[],
        )

    async def empty(*_a: object, **_k: object) -> SearchResponse:
        return SearchResponse(
            query="vaccine antigens", source="x", results=[], citations=[]
        )

    monkeypatch.setattr(svc._semanticscholar, "search", fail)
    monkeypatch.setattr(svc._europepmc, "search", good)
    for client in (
        svc._crossref,
        svc._openalex,
        svc._pubmed,
        svc._arxiv,
        svc._preprint,
    ):
        monkeypatch.setattr(client, "search", empty)

    resp = await svc.search("vaccine antigens", source="all", limit=5)
    assert [r.title for r in resp.results] == ["Good paper"]
