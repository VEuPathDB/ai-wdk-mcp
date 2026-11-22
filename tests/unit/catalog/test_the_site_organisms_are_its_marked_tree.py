"""The site's organisms are the leaves of the parameter its taxon search marks."""

from __future__ import annotations

import pytest
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import WDKTreeBoxVocabNode, WDKVocabNodeData
from veupathdb.domain.strategy import StepValidation
from veupathdb.wdk import (
    WDKEnumParam,
    WDKParameter,
    WDKSearch,
    WDKSearchResponse,
    WDKStringParam,
)

from veupathdb_mcp.catalog import organisms
from veupathdb_mcp.catalog.organisms import TAXON_SEARCH, list_organisms

SITE = "plasmodb"
SITE_ORGANISMS = ["Plasmodium berghei ANKA", "Plasmodium falciparum 3D7"]
MARK = {
    "organismProperties": [
        "pruneNodesWithSingleExtendingChild",
        "showOnlyPreferredOrganisms",
        "highlightReferenceOrganisms",
    ]
}


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


def _taxon_param(name: str, properties: dict[str, list[str]]) -> WDKEnumParam:
    return WDKEnumParam(
        name=name,
        display_name="Organism",
        type="multi-pick-vocabulary",
        display_type="treeBox",
        properties=properties,
        vocabulary=_tree(),
    )


def _taxon_response(*parameters: WDKParameter) -> WDKSearchResponse:
    return WDKSearchResponse(
        search_data=WDKSearch(
            url_segment=TAXON_SEARCH,
            display_name=TAXON_SEARCH,
            parameters=list(parameters),
        ),
        validation=StepValidation(level="SEMANTIC", is_valid=True),
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
        self.asked: list[SearchContext] = []

    async def get_catalog(self, site_id: str) -> _Catalog:
        del site_id
        return self._catalog

    async def get_search_details(self, ctx: SearchContext) -> WDKSearchResponse:
        self.asked.append(ctx)
        return self._response


def _install(monkeypatch: pytest.MonkeyPatch, discovery: _Discovery) -> None:
    monkeypatch.setattr(organisms, "get_discovery_service", lambda: discovery)


async def test_the_site_organisms_are_the_marked_trees_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _taxon_response(_taxon_param("organism", MARK))
    _install(monkeypatch, _Discovery("genomic-sequence", response))

    assert await list_organisms(SITE) == SITE_ORGANISMS


async def test_the_marked_parameter_is_read_whatever_its_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _taxon_response(
        _taxon_param("organism", {}), _taxon_param("organism_select_all", MARK)
    )
    _install(monkeypatch, _Discovery("genomic-sequence", response))

    assert await list_organisms(SITE) == SITE_ORGANISMS


async def test_a_parameter_named_organism_without_the_mark_declares_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _taxon_response(_taxon_param("organism", {}))
    _install(monkeypatch, _Discovery("genomic-sequence", response))

    assert await list_organisms(SITE) == []


async def test_a_site_without_the_taxon_search_declares_no_organisms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _taxon_response(_taxon_param("organism", MARK))
    _install(monkeypatch, _Discovery(None, response))

    assert await list_organisms(SITE) == []


async def test_a_taxon_search_without_an_organism_parameter_declares_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _taxon_response(WDKStringParam(name="text", display_name="Text"))
    _install(monkeypatch, _Discovery("genomic-sequence", response))

    assert await list_organisms(SITE) == []


async def test_the_search_details_are_read_from_the_site_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery = _Discovery(
        "genomic-sequence", _taxon_response(_taxon_param("organism", MARK))
    )
    _install(monkeypatch, discovery)

    await list_organisms(SITE)

    assert discovery.asked == [
        SearchContext(
            site_id=SITE, record_type="genomic-sequence", search_name=TAXON_SEARCH
        )
    ]
