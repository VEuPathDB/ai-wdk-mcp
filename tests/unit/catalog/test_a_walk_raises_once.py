"""A walk names every problem of a call once, in call order, with one row shape."""

from __future__ import annotations

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from tests._support.recorded_searches import recorded_search
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    SHOWN_CANDIDATES,
    VocabularyEntryError,
    entry_name,
    rank_entries,
)
from veupathdb.errors import ValidationError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter, WDKStringParam, phyletic_tree_of

from veupathdb_mcp.catalog import (
    ParamIntent,
    read_under_parents,
    resolve_params_with_intent,
)
from veupathdb_mcp.catalog.param_dag import ParamFetcher
from veupathdb_mcp.catalog.taxonomy import ORTHOMCL_PHYLETIC_SEARCH
from veupathdb_mcp.catalog.vocab_resolve import ResolveContext

from .conftest import PHYLETIC_MAPS, serving
from .test_a_filter_statement_binds_by_its_facet import (
    ngs_snps,
    variant_characteristics,
)
from .test_a_held_child_follows_a_changed_parent import _HELD, _PCHA
from .test_a_read_gathers_every_pass import _interpro
from .test_a_read_names_every_miss import _ABOUT, _PF, _rows
from .test_a_value_is_read_under_its_parents import _VIVAX, _organism, _text

_ORTHOLOGS = "search_genes_by_ortholog_pattern"

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json", f"wdk/{_ORTHOLOGS}.json"),
    reason=NEEDS_QA_RECORDING,
)


def _orthologs() -> list[WDKParameter]:
    return recorded_search(_ORTHOLOGS).search_data.parameters or []


async def _walked(
    declarations: list[WDKParameter],
    stated: dict[str, JsonValue],
    about: ResolveContext | None = None,
    search_name: str = "GenesByNgsSnps",
    site_id: str = "plasmodb",
) -> ValidationError:
    with pytest.raises(ValidationError) as refused:
        await resolve_params_with_intent(
            fetch_at=serving(*declarations),
            filter_reads=FilterReadsDouble(),
            intent=ParamIntent(),
            search=SearchContext(site_id, "transcript", search_name),
            stated=stated,
            about=about,
        )
    return refused.value


async def _read(
    stated: dict[str, JsonValue], about: ResolveContext | None = None
) -> ValidationError:
    with pytest.raises(ValidationError) as refused:
        await read_under_parents(
            serving(*ngs_snps()), stated, FilterReadsDouble(), about=about
        )
    return refused.value


async def test_a_species_list_of_the_wrong_shape_is_named_as_its_shape() -> None:
    refusal = await _walked(
        _orthologs(),
        {"included_species": {"x": 1}},
        search_name="GenesByOrthologPattern",
    )

    rows = _rows(refusal)
    assert [row.param for row in rows] == ["included_species"]
    assert "select no species" not in str(refusal.detail)


async def test_a_phyletic_refusal_and_an_organism_fault_are_one_refusal() -> None:
    refusal = await _walked(
        _orthologs(),
        {"organism": ["Pf3D8"], "included_species": "no such species"},
        search_name="GenesByOrthologPattern",
    )

    assert [row.param for row in _rows(refusal)] == ["organism", "included_species"]


async def test_a_species_list_that_names_no_species_is_refused_on_itself() -> None:
    refusal = await _walked(
        _orthologs(),
        {"included_species": "no such species", "organism": ["Pf3D8"]},
        search_name="GenesByOrthologPattern",
    )

    [species, organism] = _rows(refusal)
    assert (species.param, organism.param) == ("included_species", "organism")
    assert species.value == "no such species"
    assert species.detail.startswith(
        "included_species names no entry ['no such species']. Nearest entries: "
    )


async def test_each_species_list_that_names_no_species_has_its_own_row() -> None:
    refusal = await _walked(
        _orthologs(),
        {"excluded_species": "no such clade", "included_species": "no such species"},
        search_name="GenesByOrthologPattern",
    )

    rows = _rows(refusal)
    assert [(row.param, row.value) for row in rows] == [
        ("excluded_species", "no such clade"),
        ("included_species", "no such species"),
    ]


async def test_naming_neither_list_selects_no_species() -> None:
    refusal = await _walked(
        _orthologs(), {"organism": ["Pf3D8"]}, search_name="GenesByOrthologPattern"
    )

    rows = _rows(refusal)
    assert [row.param for row in rows] == ["organism", "profile_pattern"]
    assert "select no species" in rows[1].detail


def _without_the_tree() -> list[WDKParameter]:
    return [
        WDKStringParam(name=d.name, is_visible=False, allow_empty_value=True)
        if d.name in PHYLETIC_MAPS
        else d
        for d in _orthologs()
    ]


async def test_a_search_whose_tree_does_not_read_names_its_maps() -> None:
    refusal = await _walked(
        _without_the_tree(),
        {"included_species": "pfal", "organism": ["Pf3D8"]},
        search_name="GenesByOrthologPattern",
    )

    rows = _rows(refusal)
    assert [row.param for row in rows] == ["organism", "profile_pattern"]
    assert "select no species" not in str(refusal.detail)
    assert "phyletic_indent_map and phyletic_term_map" in rows[1].detail


async def test_an_unknown_name_and_an_unnamed_entry_are_one_read_refusal() -> None:
    refusal = await _read(
        {"organismSinglePick": _PF, "no_such": "x", "snp_class": "non-synonymous"}
    )

    assert [row.param for row in _rows(refusal)] == ["no_such", "snp_class"]


async def test_the_walk_joins_an_unknown_name_with_an_unnamed_entry() -> None:
    refusal = await _walked(ngs_snps(), {"snp_class": "non-synonymous", "no_such": "x"})

    assert [row.param for row in _rows(refusal)] == ["snp_class", "no_such"]


async def test_a_site_set_name_and_an_unnamed_entry_are_one_refusal() -> None:
    refusal = await _walked(
        ngs_snps(), {"WebServicesPath": "dflt", "snp_class": "non-synonymous"}
    )

    assert [row.param for row in _rows(refusal)] == ["WebServicesPath", "snp_class"]


async def test_an_unset_site_value_and_an_unnamed_entry_are_one_refusal() -> None:
    unset = WDKStringParam(name="site_only", is_visible=False, allow_empty_value=False)

    refusal = await _walked([*ngs_snps(), unset], {"snp_class": "non-synonymous"})

    assert [row.param for row in _rows(refusal)] == ["snp_class", "site_only"]


async def test_an_unread_name_row_names_its_parameter() -> None:
    refusal = await _read(
        {"organismSinglePick": _PF, "snp_class": "non-synonymous", "no_such": "x"}
    )

    [_, unknown] = _rows(refusal)
    assert "no_such" in unknown.detail


@pytest.mark.parametrize(
    "stated",
    [
        {"organismSinglePick": _PF, "no_such": "x", "snp_class": "non-synonymous"},
        {"MinPercentMinorAlleles": {"x": 1}, "snp_class": "non-synonymous"},
        {"ReadFrequencyPercent": "95 percent", "snp_class": "non-synonymous"},
    ],
)
async def test_a_refusal_is_the_same_whatever_about_is(
    stated: dict[str, JsonValue],
) -> None:
    unordered = await _read(stated)
    ordered = await _read(stated, _ABOUT)

    assert type(ordered) is type(unordered)
    assert ordered.errors == unordered.errors
    assert ordered.detail == unordered.detail
    assert ordered.title == unordered.title


async def test_a_mixed_refusal_is_a_plain_row_refusal() -> None:
    refusal = await _read({"MinPercentMinorAlleles": {"x": 1}, "snp_class": "x"})

    assert type(refusal) is ValidationError
    assert not isinstance(refusal, VocabularyEntryError)


async def test_an_unread_name_and_an_unknown_name_are_one_refusal() -> None:
    first = [_organism((_VIVAX, _VIVAX), dependents=("strain",)), _text("strain")]

    refusal = await _read_by(
        _first_then(first, [first[0]]),
        {"organism": [_VIVAX], "strain": "x", "no_such": "y"},
    )

    [strain, unknown] = _rows(refusal)
    assert (strain.param, unknown.param) == ("strain", "no_such")
    assert strain.detail == (
        "No read under the stated parents declares strain, so its value cannot be read."
    )


async def test_a_moved_parent_refusal_and_an_unnamed_entry_are_one_refusal() -> None:
    with pytest.raises(ValidationError) as refused:
        await read_under_parents(
            serving(*variant_characteristics(), *_interpro()),
            {
                "organism_select_none": [_PCHA],
                "organism": _PF,
                "domain_database": "InterPro",
                "domain_typeahead": ["serine/threonine protein kinase"],
            },
            FilterReadsDouble(
                {"total_variants": "ontology_term_summary_total_variants"}
            ),
            about=None,
            bound=_HELD,
        )

    rows = _rows(refused.value)
    assert [row.param for row in rows] == ["domain_typeahead", "gene_variant_stats"]
    assert rows[1].detail.startswith("organism_select_none moved from")


async def _read_by(
    fetch_at: ParamFetcher, stated: dict[str, JsonValue]
) -> ValidationError:
    with pytest.raises(ValidationError) as refused:
        await read_under_parents(fetch_at, stated, FilterReadsDouble(), about=None)
    return refused.value


def _first_then(first: list[WDKParameter], later: list[WDKParameter]) -> ParamFetcher:
    seen: list[dict[str, str]] = []

    async def fetch_at(context: dict[str, str]) -> list[WDKParameter]:
        seen.append(dict(context))
        return first if len(seen) == 1 else later

    return fetch_at


def _nearest_to(term: str) -> str:
    tree = phyletic_tree_of(_orthologs())
    assert tree is not None
    ranked = rank_entries(tree.labels(), term, SHOWN_CANDIDATES)
    return ", ".join(entry_name(entry) for entry in ranked)


@pytest.mark.parametrize("about", [None, _ABOUT])
async def test_each_species_list_is_offered_its_own_nearest_entries(
    about: ResolveContext | None,
) -> None:
    refusal = await _walked(
        _orthologs(),
        {
            "included_species": "Plasmodium falciparum",
            "excluded_species": "Homo sapienz",
        },
        about=about,
        search_name="GenesByOrthologPattern",
    )

    [included, excluded] = _rows(refusal)
    assert included.detail.endswith(
        f"Nearest entries: {_nearest_to('Plasmodium falciparum')}."
    )
    assert excluded.detail.endswith(f"Nearest entries: {_nearest_to('Homo sapienz')}.")
    assert _nearest_to("Plasmodium falciparum") != _nearest_to("Homo sapienz")


_NO_TREE = (
    "The site's species tree does not read: its phyletic_indent_map and "
    "phyletic_term_map give no tree, so included_species and excluded_species "
    "derive no profile_pattern, and restating them cannot fix it."
)


async def _no_tree_on(site_id: str) -> str:
    refusal = await _walked(
        _without_the_tree(),
        {"included_species": "pfal"},
        search_name="GenesByOrthologPattern",
        site_id=site_id,
    )
    [pattern] = _rows(refusal)
    return pattern.detail


async def test_a_component_site_whose_tree_does_not_read_names_orthomcl() -> None:
    assert await _no_tree_on("plasmodb") == (
        f"{_NO_TREE} Take another route: OrthoMCL's Phyletic Pattern search "
        f"({ORTHOMCL_PHYLETIC_SEARCH}) states the pattern as a phyletic_expression "
        "against OrthoMCL's own tree."
    )
    assert ORTHOMCL_PHYLETIC_SEARCH == "GroupsByPhyleticPattern"


async def test_orthomcl_whose_tree_does_not_read_names_no_route() -> None:
    assert await _no_tree_on("orthomcl") == _NO_TREE


async def test_a_code_both_lists_name_is_refused_on_each_list() -> None:
    refusal = await _walked(
        _orthologs(),
        {"excluded_species": "pfal", "included_species": "pfal"},
        search_name="GenesByOrthologPattern",
    )

    rows = _rows(refusal)
    assert [(row.param, row.value) for row in rows] == [
        ("excluded_species", "pfal"),
        ("included_species", "pfal"),
    ]
    assert all("both name ['pfal']" in row.detail for row in rows)
