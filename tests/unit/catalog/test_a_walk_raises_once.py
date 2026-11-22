"""A walk names every problem of a call once, in call order, with one row shape."""

from __future__ import annotations

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from tests._support.recorded_searches import recorded_search
from veupathdb.domain.parameters import VocabularyEntryError
from veupathdb.errors import ValidationError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter, WDKStringParam

from veupathdb_mcp.catalog import (
    ParamIntent,
    read_under_parents,
    resolve_params_with_intent,
)
from veupathdb_mcp.catalog.vocab_resolve import ResolveContext

from .conftest import serving
from .test_a_filter_statement_binds_by_its_facet import ngs_snps
from .test_a_read_names_every_miss import _ABOUT, _PF, _rows

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
) -> ValidationError:
    with pytest.raises(ValidationError) as refused:
        await resolve_params_with_intent(
            fetch_at=serving(*declarations),
            filter_reads=FilterReadsDouble(),
            intent=ParamIntent(),
            search_name=search_name,
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

    assert [row.param for row in _rows(refusal)] == ["organism", "profile_pattern"]


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
