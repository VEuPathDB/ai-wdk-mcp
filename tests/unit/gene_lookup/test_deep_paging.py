"""Gene text lookup past the fifty records one site-search page holds."""

from __future__ import annotations

import pytest

from veupathdb_mcp.gene_lookup import lookup, site_search
from veupathdb_mcp.gene_lookup.lookup import lookup_genes_by_text
from veupathdb_mcp.gene_lookup.result import GeneResult
from veupathdb_mcp.gene_lookup.site_search import (
    SITE_SEARCH_PAGE_LIMIT,
    stream_site_search_gene_ids,
)
from veupathdb_mcp.gene_lookup.wdk import WdkTextResult

MATCHED_GENES = 352
"""What plasmodb answers for the fixture query; one page carries fifty."""

_PAGE = [
    GeneResult(
        gene_id=f"PF3D7_{i:06d}",
        display_name=f"kinase {i}",
        organism="Plasmodium falciparum 3D7",
        product=f"kinase {i}",
    )
    for i in range(SITE_SEARCH_PAGE_LIMIT)
]
_ALL_IDS = [f"PF3D7_{i:06d}" for i in range(MATCHED_GENES)]


class _Recorder:
    """Remembers what the stream was asked for, and answers with the match set."""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.organisms: list[list[str] | None] = []

    async def __call__(
        self,
        site_id: str,
        search_text: str,
        *,
        organisms: list[str] | None = None,
        max_records: int,
    ) -> list[str]:
        del site_id, search_text
        self.calls.append(max_records)
        self.organisms.append(organisms)
        return _ALL_IDS[:max_records]


@pytest.fixture
def streamed(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Replace every network call the lookup makes, and watch the stream."""
    recorder = _Recorder()

    async def page(
        site_id: str,
        search_text: str,
        *,
        organisms: list[str] | None = None,
        limit: int = SITE_SEARCH_PAGE_LIMIT,
    ) -> tuple[list[GeneResult], list[str], int]:
        del site_id, search_text, organisms, limit
        return list(_PAGE), ["Plasmodium falciparum 3D7"], MATCHED_GENES

    async def no_wdk_text(*args: object, **kwargs: object) -> WdkTextResult:
        del args, kwargs
        return WdkTextResult(records=[], total_count=0)

    async def hydrate(site_id: str, results: list[GeneResult]) -> list[GeneResult]:
        del site_id
        return [
            r
            if r.product
            else GeneResult(
                gene_id=r.gene_id,
                display_name=f"hydrated {r.gene_id}",
                organism="Plasmodium falciparum 3D7",
                product="protein kinase",
            )
            for r in results
        ]

    monkeypatch.setattr(lookup, "fetch_site_search_genes", page)
    monkeypatch.setattr(lookup, "stream_site_search_gene_ids", recorder)
    monkeypatch.setattr(lookup, "fetch_wdk_text_genes", no_wdk_text)
    monkeypatch.setattr(lookup, "hydrate_sparse_gene_results", hydrate)
    return recorder


@pytest.mark.asyncio
async def test_the_first_page_reads_no_stream(streamed: _Recorder) -> None:
    result = await lookup_genes_by_text("plasmodb", "kinase", offset=0, limit=30)

    assert streamed.calls == []
    assert [r.gene_id for r in result.records] == _ALL_IDS[:30]


@pytest.mark.asyncio
async def test_the_count_is_what_site_search_matched_not_what_a_page_held(
    streamed: _Recorder,
) -> None:
    """A caller cannot page to what the count does not admit."""
    del streamed
    result = await lookup_genes_by_text("plasmodb", "kinase", offset=0, limit=30)

    assert result.total_count == MATCHED_GENES


@pytest.mark.asyncio
async def test_a_page_past_the_paged_ceiling_is_served_from_the_stream(
    streamed: _Recorder,
) -> None:
    result = await lookup_genes_by_text("plasmodb", "kinase", offset=90, limit=30)

    assert streamed.calls == [120]
    assert [r.gene_id for r in result.records] == _ALL_IDS[90:120]
    assert result.total_count == MATCHED_GENES


@pytest.mark.asyncio
async def test_a_streamed_record_reaches_the_caller_described(
    streamed: _Recorder,
) -> None:
    """The stream carries an identifier only, so the window is hydrated."""
    del streamed
    result = await lookup_genes_by_text("plasmodb", "kinase", offset=90, limit=2)

    assert [(r.gene_id, r.product) for r in result.records] == [
        ("PF3D7_000090", "protein kinase"),
        ("PF3D7_000091", "protein kinase"),
    ]


@pytest.mark.asyncio
async def test_the_paged_records_keep_their_rank_ahead_of_the_stream(
    streamed: _Recorder,
) -> None:
    del streamed
    result = await lookup_genes_by_text("plasmodb", "kinase", offset=0, limit=60)

    assert [r.gene_id for r in result.records[:SITE_SEARCH_PAGE_LIMIT]] == [
        r.gene_id for r in _PAGE
    ]
    assert [r.gene_id for r in result.records[SITE_SEARCH_PAGE_LIMIT:]] == _ALL_IDS[
        SITE_SEARCH_PAGE_LIMIT:60
    ]


@pytest.mark.asyncio
async def test_the_streamed_identifiers_are_deduplicated_in_service_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Client:
        async def stream_records(
            self,
            search_text: str,
            *,
            document_type: str,
            organisms: list[str] | None = None,
            max_records: int,
        ) -> list[object]:
            del search_text, document_type, organisms, max_records
            return [
                _Record(["PF3D7_0616000"]),
                _Record(["PF3D7_0626800"]),
                _Record(["PF3D7_0616000"]),
                _Record([]),
                _Record([" PF3D7_0922500 "]),
            ]

    class _Record:
        def __init__(self, primary_key: list[str]) -> None:
            self.primary_key = primary_key

    class _Router:
        def get_site_search_client(self, site_id: str) -> _Client:
            del site_id
            return _Client()

    monkeypatch.setattr(site_search, "get_site_router", _Router)

    assert await stream_site_search_gene_ids("plasmodb", "kinase") == [
        "PF3D7_0616000",
        "PF3D7_0626800",
        "PF3D7_0922500",
    ]


@pytest.mark.asyncio
async def test_a_named_organism_restricts_the_stream_as_well_as_the_count(
    streamed: _Recorder,
) -> None:
    """A count the stream cannot reach would promise a page that never loads."""
    result = await lookup_genes_by_text(
        "plasmodb",
        "kinase",
        organism="Plasmodium falciparum 3D7",
        offset=60,
        limit=10,
    )

    assert streamed.organisms == [["Plasmodium falciparum 3D7"]]
    assert [r.gene_id for r in result.records] == _ALL_IDS[60:70]
