"""OrthoMCL's taxonomy is read once per site and serves the phyletic code lookup."""

from __future__ import annotations

from typing import Any

import pytest
from veupathdb.domain.parameters import PhyleticTree, TaxonEntry
from veupathdb.wdk import WDKAnswer, WDKRecordType, WDKSearch, WDKStringParam

from veupathdb_mcp.catalog import ortho_taxonomy, param_phyletic
from veupathdb_mcp.catalog.param_phyletic import EXPRESSION_LOOKUP_HINT, LOOKUP_HINT

_TABLES = {
    "RootTaxons": [
        {
            "orthomcl_clade_id": "1",
            "parent_id": None,
            "taxon_abbrev": "ALL",
            "name": "Root",
        },
        {
            "orthomcl_clade_id": "2",
            "parent_id": "1",
            "taxon_abbrev": "HAEM",
            "name": "Haemosporida",
        },
    ],
    "Taxons": [
        {
            "orthomcl_clade_id": "3",
            "parent_id": "2",
            "three_letter_abbrev": "pfal",
            "name": "Plasmodium falciparum 3D7",
        },
    ],
}


class _Client:
    def __init__(self) -> None:
        self.reports: list[tuple[str, str]] = []

    async def run_search_report(
        self, record_type: str, search_name: str, *_: Any, **__: Any
    ) -> WDKAnswer:
        self.reports.append((record_type, search_name))
        return WDKAnswer.model_validate(
            {"meta": {"totalCount": 1}, "records": [{"tables": _TABLES}]}
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    served = _Client()
    monkeypatch.setattr(ortho_taxonomy, "get_wdk_client", lambda _site: served)
    monkeypatch.setattr(ortho_taxonomy, "_HELD", {})
    return served


async def test_the_taxonomy_is_the_helper_records_tables(client: _Client) -> None:
    tree = await ortho_taxonomy.ortho_taxonomy("orthomcl")

    assert tree is not None
    assert [node.code for node in tree.nodes()] == ["HAEM", "pfal"]
    assert client.reports == [("helper", "ByDefault")]


async def test_the_taxonomy_is_read_once_per_site(client: _Client) -> None:
    await ortho_taxonomy.ortho_taxonomy("orthomcl")
    await ortho_taxonomy.ortho_taxonomy("orthomcl")

    assert len(client.reports) == 1


class _Discovery:
    def __init__(self, searches: dict[str, list[str]]) -> None:
        self._searches = searches

    async def get_record_types(self, site_id: str) -> list[WDKRecordType]:
        del site_id
        return [WDKRecordType(url_segment=name) for name in self._searches]

    async def get_searches(self, site_id: str, record_type: str) -> list[WDKSearch]:
        del site_id
        return [
            WDKSearch(url_segment=name, full_name=name, display_name=name)
            for name in self._searches[record_type]
        ]


def _tree() -> PhyleticTree:
    return PhyleticTree.from_taxa(
        [
            TaxonEntry(
                id="3", parent_id=None, code="pfal", label="Plasmodium falciparum 3D7"
            )
        ]
    )


@pytest.fixture
def unranked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _tree_order(
        _query: str, candidates: list[tuple[str, str, bool]]
    ) -> list[tuple[str, str, bool]]:
        return candidates

    monkeypatch.setattr(param_phyletic, "_rank_by_semantic_similarity", _tree_order)


async def test_a_site_with_the_expression_search_looks_codes_up_in_its_taxonomy(
    monkeypatch: pytest.MonkeyPatch, unranked: None
) -> None:
    del unranked
    discovery = _Discovery({"group": ["GroupsByPhyleticPattern"], "sequence": []})
    monkeypatch.setattr(param_phyletic, "get_discovery_service", lambda: discovery)

    async def _taxonomy(site_id: str) -> PhyleticTree:
        assert site_id == "orthomcl"
        return _tree()

    monkeypatch.setattr(param_phyletic, "ortho_taxonomy", _taxonomy)

    found = await param_phyletic.lookup_phyletic_codes("orthomcl", "transcript", "3D7")

    assert found == {
        "query": "3D7",
        "matches": [
            {"code": "pfal", "label": "Plasmodium falciparum 3D7", "leaf": True}
        ],
        "total": 1,
        "hint": EXPRESSION_LOOKUP_HINT,
    }


def test_the_two_hints_name_the_parameter_each_search_takes() -> None:
    assert "phyletic_expression" in EXPRESSION_LOOKUP_HINT
    assert "included_species" not in EXPRESSION_LOOKUP_HINT
    assert "included_species" in LOOKUP_HINT


async def test_every_entry_that_names_each_known_query_word_is_returned_past_the_cap(
    unranked: None,
) -> None:
    del unranked
    strains = [f"Plasmodium falciparum S{n}" for n in range(25)]
    tree = PhyleticTree.from_taxa(
        [
            TaxonEntry(
                id="p",
                parent_id=None,
                code="ppra",
                label="Plasmodium praefalciparum G01",
            ),
            *(
                TaxonEntry(id=str(n), parent_id=None, code=f"pf{n:02d}", label=label)
                for n, label in enumerate(strains)
            ),
        ]
    )

    matches = await param_phyletic._match_phyletic_entries(
        tree, "plasmodium falciparum"
    )

    assert [m["label"] for m in matches] == strains


async def test_the_expression_search_names_its_codes_from_the_taxonomy(
    client: _Client,
) -> None:
    del client
    definition = WDKSearch(
        url_segment="GroupsByPhyleticPattern",
        full_name="GroupsByPhyleticPattern",
        display_name="Phyletic Pattern",
        parameters=[WDKStringParam(name="phyletic_expression")],
    )

    tree = await ortho_taxonomy.phyletic_tree_for_search("orthomcl", definition)

    assert tree is not None
    assert tree.codes() == {"HAEM", "pfal"}


async def test_a_search_with_no_species_codes_has_no_tree(client: _Client) -> None:
    definition = WDKSearch(
        url_segment="GroupsByText",
        full_name="GroupsByText",
        display_name="Text",
        parameters=[WDKStringParam(name="text_expression")],
    )

    assert await ortho_taxonomy.phyletic_tree_for_search("orthomcl", definition) is None
    assert client.reports == []
