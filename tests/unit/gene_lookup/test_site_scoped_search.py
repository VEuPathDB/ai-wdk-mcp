"""A gene search is restricted to the site's own organisms.

Site search serves one SOLR index for every VEuPathDB site and does not filter
gene documents by project, so a query that names no organism answers with every
site's genes. The site's own organism list is what keeps the answer on the site
the caller chose, which is what VEuPathDB's own client sends.
"""

from __future__ import annotations

import pytest
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import WDKTreeBoxVocabNode, WDKVocabNodeData
from veupathdb.domain.strategy import StepValidation
from veupathdb.wdk import (
    DocumentTypeFilter,
    SiteSearchResponse,
    SiteSearchStreamRecord,
    WDKEnumParam,
    WDKSearch,
    WDKSearchResponse,
    WDKStringParam,
)

from veupathdb_mcp import gene_lookup
from veupathdb_mcp.gene_lookup.organisms import (
    ORGANISM_PARAM,
    TAXON_SEARCH,
    list_organisms,
)
from veupathdb_mcp.gene_lookup.site_search import (
    fetch_site_search_genes,
    stream_site_search_gene_ids,
)

SITE = "plasmodb"
SITE_ORGANISMS = ["Plasmodium berghei ANKA", "Plasmodium falciparum 3D7"]
_VALID = StepValidation(level="SEMANTIC", is_valid=True)


class _Recorder:
    """The site-search client, remembering what each form was asked for."""

    def __init__(self) -> None:
        self.searched: list[list[str] | None] = []
        self.metadata: list[list[str] | None] = []
        self.streamed: list[list[str] | None] = []

    async def search(
        self,
        search_text: str,
        *,
        document_type_filter: DocumentTypeFilter | None = None,
        organisms: list[str] | None = None,
        restrict_metadata_to_organisms: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SiteSearchResponse:
        del search_text, document_type_filter, limit, offset
        self.searched.append(organisms)
        self.metadata.append(restrict_metadata_to_organisms)
        return SiteSearchResponse()

    async def stream_records(
        self,
        search_text: str,
        *,
        document_type: str,
        organisms: list[str] | None = None,
        max_records: int,
    ) -> list[SiteSearchStreamRecord]:
        del search_text, document_type, max_records
        self.streamed.append(organisms)
        return []


class _Router:
    def __init__(self, client: _Recorder) -> None:
        self._client = client

    def get_site_search_client(self, site_id: str) -> _Recorder:
        del site_id
        return self._client


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    client = _Recorder()
    monkeypatch.setattr(
        gene_lookup.site_search, "get_site_router", lambda: _Router(client)
    )

    async def site_organisms(site_id: str) -> list[str]:
        del site_id
        return list(SITE_ORGANISMS)

    monkeypatch.setattr(gene_lookup.site_search, "list_organisms", site_organisms)
    return client


async def test_a_search_without_an_organism_names_the_sites_own(
    recorder: _Recorder,
) -> None:
    await fetch_site_search_genes(SITE, "kinase")

    assert recorder.searched == [SITE_ORGANISMS]


async def test_a_search_with_organisms_names_exactly_those(
    recorder: _Recorder,
) -> None:
    await fetch_site_search_genes(SITE, "kinase", organisms=["Plasmodium vivax P01"])

    assert recorder.searched == [["Plasmodium vivax P01"]]


async def test_the_organism_facet_is_the_sites_own_list(
    recorder: _Recorder,
) -> None:
    """``organismCounts`` is what the caller offers as the organism filter."""
    await fetch_site_search_genes(SITE, "kinase", organisms=["Plasmodium vivax P01"])

    assert recorder.metadata == [SITE_ORGANISMS]


async def test_the_stream_is_restricted_the_same_way(recorder: _Recorder) -> None:
    await stream_site_search_gene_ids(SITE, "kinase", max_records=10)

    assert recorder.streamed == [SITE_ORGANISMS]


async def test_a_site_that_declares_no_organisms_sends_no_restriction(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def none(site_id: str) -> list[str]:
        del site_id
        return []

    monkeypatch.setattr(gene_lookup.site_search, "list_organisms", none)

    await fetch_site_search_genes(SITE, "kinase")
    await stream_site_search_gene_ids(SITE, "kinase", max_records=10)

    assert recorder.searched == [None]
    assert recorder.streamed == [None]


def _taxon_response(vocabulary: WDKTreeBoxVocabNode) -> WDKSearchResponse:
    return WDKSearchResponse(
        search_data=WDKSearch(
            url_segment=TAXON_SEARCH,
            display_name=TAXON_SEARCH,
            parameters=[
                WDKEnumParam(
                    name=ORGANISM_PARAM,
                    display_name="Organism",
                    type="multi-pick-vocabulary",
                    display_type="treeBox",
                    vocabulary=vocabulary,
                ),
            ],
        ),
        validation=_VALID,
    )


def _tree() -> WDKTreeBoxVocabNode:
    return WDKTreeBoxVocabNode(
        data=WDKVocabNodeData(term="root", display="root"),
        children=[
            WDKTreeBoxVocabNode(
                data=WDKVocabNodeData(term="Plasmodium", display="Plasmodium"),
                children=[
                    WDKTreeBoxVocabNode(data=WDKVocabNodeData(term=name, display=name))
                    for name in SITE_ORGANISMS
                ],
            ),
        ],
    )


class _Catalog:
    def __init__(self, record_type: str | None) -> None:
        self._record_type = record_type

    def find_record_type_for_search(self, search_name: str) -> str | None:
        assert search_name == TAXON_SEARCH
        return self._record_type


class _Discovery:
    def __init__(self, record_type: str | None, response: WDKSearchResponse) -> None:
        self._catalog = _Catalog(record_type)
        self._response = response
        self.asked: list[str] = []

    async def get_catalog(self, site_id: str) -> _Catalog:
        del site_id
        return self._catalog

    async def get_search_details(
        self, ctx: object, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del expand_params
        self.asked.append(str(ctx))
        return self._response


def _install(monkeypatch: pytest.MonkeyPatch, discovery: _Discovery) -> None:
    monkeypatch.setattr(
        gene_lookup.organisms, "get_discovery_service", lambda: discovery
    )


async def test_the_site_organisms_are_the_taxon_trees_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _Discovery("genomic-sequence", _taxon_response(_tree())))

    assert await list_organisms(SITE) == SITE_ORGANISMS


async def test_a_site_without_the_taxon_search_declares_no_organisms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _Discovery(None, _taxon_response(_tree())))

    assert await list_organisms(SITE) == []


async def test_a_taxon_search_without_the_organism_parameter_declares_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = WDKSearchResponse(
        search_data=WDKSearch(
            url_segment=TAXON_SEARCH,
            display_name=TAXON_SEARCH,
            parameters=[
                WDKStringParam(name="text", display_name="Text"),
            ],
        ),
        validation=_VALID,
    )
    _install(monkeypatch, _Discovery("genomic-sequence", response))

    assert await list_organisms(SITE) == []


async def test_the_search_details_are_read_from_the_site_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog caches the response, so the vocabulary is fetched once."""
    discovery = _Discovery("genomic-sequence", _taxon_response(_tree()))
    _install(monkeypatch, discovery)

    await list_organisms(SITE)

    assert discovery.asked == [
        str(
            SearchContext(
                site_id=SITE, record_type="genomic-sequence", search_name=TAXON_SEARCH
            )
        )
    ]
