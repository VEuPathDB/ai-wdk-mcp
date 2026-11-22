"""OrthoMCL's taxonomy is read once per site and serves the phyletic code lookup."""

from __future__ import annotations

from typing import Any

import pytest
from tests._support.record_types import RecordedRecordTypes
from veupathdb.domain.parameters import PhyleticNode, PhyleticTree, TaxonEntry
from veupathdb.errors import ValidationError
from veupathdb.wdk import WDKAnswer, WDKSearch, WDKStringParam

from veupathdb_mcp.catalog import group_counts, param_phyletic, taxonomy
from veupathdb_mcp.catalog.group_counts import site_taxonomy
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


def _serve(monkeypatch: pytest.MonkeyPatch) -> _Client:
    served = _Client()
    monkeypatch.setattr(taxonomy, "get_wdk_client", lambda _site: served)
    monkeypatch.setattr(taxonomy, "_HELD", {})
    return served


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    return _serve(monkeypatch)


async def test_a_site_with_no_helper_record_type_has_no_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served = _serve(monkeypatch)

    assert await taxonomy.ortho_taxonomy("plasmodb") is None
    assert served.reports == []


async def test_a_site_with_no_taxonomy_refuses_an_expression_with_its_own_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch)

    with pytest.raises(ValidationError) as refusal:
        await site_taxonomy("plasmodb")

    assert refusal.value.detail == (
        "plasmodb serves no OrthoMCL taxonomy and no search that takes "
        "phyletic_expression; only OrthoMCL's GroupsByPhyleticPattern does. On "
        "plasmodb, GenesByOrthologPattern states a phyletic profile: put the codes "
        "lookup_phyletic_codes returns in included_species and excluded_species."
    )


async def test_the_taxonomy_is_the_helper_records_tables(client: _Client) -> None:
    tree = await taxonomy.ortho_taxonomy("orthomcl")

    assert tree is not None
    assert [node.code for node in tree.nodes()] == ["HAEM", "pfal"]
    assert client.reports == [("helper", "ByDefault")]


@pytest.mark.parametrize(
    ("site_id", "serves"), [("orthomcl", True), ("plasmodb", False)]
)
async def test_a_site_serves_the_taxonomy_when_it_lists_the_helper_record_type(
    site_id: str, serves: bool, listed_record_types: RecordedRecordTypes
) -> None:
    assert await taxonomy.serves_ortho_taxonomy(site_id) is serves
    assert await taxonomy.serves_ortho_taxonomy(site_id) is serves
    assert listed_record_types.asked == [site_id]


async def test_a_site_that_lists_the_helper_and_holds_no_tables_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch)

    async def _no_tree(site_id: str) -> None:
        del site_id

    monkeypatch.setattr(group_counts, "ortho_taxonomy", _no_tree)

    with pytest.raises(ValidationError) as refusal:
        await site_taxonomy("orthomcl")

    assert refusal.value.detail == (
        "orthomcl lists the helper record type, but its taxonomy report holds "
        "no clade or genome tables."
    )


async def test_the_taxonomy_is_read_once_per_site(client: _Client) -> None:
    await taxonomy.ortho_taxonomy("orthomcl")
    await taxonomy.ortho_taxonomy("orthomcl")

    assert len(client.reports) == 1


def _tree() -> PhyleticTree:
    return PhyleticTree.from_taxa(
        [
            TaxonEntry(
                id="3",
                parent_id=None,
                code="pfal",
                label="Plasmodium falciparum 3D7",
                clade=False,
            )
        ]
    )


@pytest.fixture
def unranked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _tree_order(
        _query: str, candidates: list[PhyleticNode]
    ) -> list[PhyleticNode]:
        return candidates

    monkeypatch.setattr(param_phyletic, "_rank_by_semantic_similarity", _tree_order)


async def test_a_site_with_the_expression_search_looks_codes_up_in_its_taxonomy(
    monkeypatch: pytest.MonkeyPatch, unranked: None
) -> None:
    del unranked
    _serve(monkeypatch)

    async def _taxonomy(site_id: str) -> PhyleticTree:
        assert site_id == "orthomcl"
        return _tree()

    monkeypatch.setattr(param_phyletic, "ortho_taxonomy", _taxonomy)

    found = await param_phyletic.lookup_phyletic_codes("orthomcl", "transcript", "3D7")

    assert found == {
        "query": "3D7",
        "matches": [
            {
                "code": "pfal",
                "label": "Plasmodium falciparum 3D7",
                "leaf": True,
                "genomes": 1,
            }
        ],
        "species": [{"species": "Plasmodium falciparum", "genomes": ["pfal"]}],
        "total": 1,
        "hint": EXPRESSION_LOOKUP_HINT,
    }


def test_the_two_hints_name_the_parameter_each_search_takes() -> None:
    assert "phyletic_expression" in EXPRESSION_LOOKUP_HINT
    assert "included_species" not in EXPRESSION_LOOKUP_HINT
    assert "included_species" in LOOKUP_HINT


def test_the_expression_hint_names_the_builder_and_counts_genomes() -> None:
    assert EXPRESSION_LOOKUP_HINT == (
        "Pass these codes to build_phyletic_expression, which writes "
        "phyletic_expression from them. A code with leaf=true is one genome (one "
        "proteome): several strains of one species are several genomes, grouped "
        "under species. A code with leaf=false is a clade, and genomes is the number "
        "of genomes under it. A clade is only what its label names, so a genus with "
        "no clade of its own is the list of its genome codes."
    )
    assert "recipe" not in EXPRESSION_LOOKUP_HINT


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
                clade=False,
            ),
            *(
                TaxonEntry(
                    id=str(n),
                    parent_id=None,
                    code=f"pf{n:02d}",
                    label=label,
                    clade=False,
                )
                for n, label in enumerate(strains)
            ),
        ]
    )

    matches, _ = await param_phyletic._match_phyletic_entries(
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

    tree = await taxonomy.phyletic_tree_for_search("orthomcl", definition)

    assert tree is not None
    assert tree.codes() == {"HAEM", "pfal"}


async def test_a_search_with_no_species_codes_has_no_tree(client: _Client) -> None:
    definition = WDKSearch(
        url_segment="GroupsByText",
        full_name="GroupsByText",
        display_name="Text",
        parameters=[WDKStringParam(name="text_expression")],
    )

    assert await taxonomy.phyletic_tree_for_search("orthomcl", definition) is None
    assert client.reports == []
