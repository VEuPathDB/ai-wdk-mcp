"""A read names the problems of every pass in one refusal, each entry led by its pick."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import JsonValue
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import VocabularyEntryError, flatten_vocab
from veupathdb.errors import ValidationError
from veupathdb.testing import NEEDS_QA_RECORDING
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog import read_under_parents
from veupathdb_mcp.catalog.param_dag import resolve_params_with_intent
from veupathdb_mcp.catalog.param_intent import ParamIntent

from .conftest import serving
from .test_a_filter_statement_binds_by_its_facet import (
    ngs_snps,
    variant_characteristics,
)
from .test_a_read_names_every_miss import (
    _ABOUT,
    _PF,
    _RECORDED,
    _led,
    _picking_the_last_offered,
    _reads,
    _rows,
)

_INTERPRO = (
    Path(__file__).parent
    / "fixtures"
    / "plasmodb_3d7_interpro_vocabulary_half_off.json"
)


def _interpro() -> list[WDKParameter]:
    recorded = json.loads(_INTERPRO.read_text())
    response = WDKSearchResponse.model_validate(recorded["response_json"])
    return response.search_data.parameters or []


_ONE_SHAPE_TWO_ENTRIES: dict[str, JsonValue] = {
    "organismSinglePick": _PF,
    "MinPercentMinorAlleles": {"x": 1},
    "ReadFrequencyPercent": "95 percent",
    "snp_class": "non-synonymous",
}

_A_MISS_THEN_AN_ENTRY: dict[str, JsonValue] = {
    "organism_select_none": _PF,
    "gene_variant_stats": [{"field": "total_variants", "value": {"min": 4824}}],
    "organism": _PF,
    "domain_database": "InterPro",
    "domain_typeahead": ["serine/threonine protein kinase"],
}


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
async def test_a_mixed_read_orders_every_entry_row_in_call_order() -> None:
    sent = _picking_the_last_offered()
    declarations = ngs_snps()
    options = {d.name: flatten_vocab(d.vocabulary) for d in declarations}

    with pytest.raises(ValidationError) as refused:
        await read_under_parents(
            serving(*declarations), _ONE_SHAPE_TWO_ENTRIES, _reads(), about=_ABOUT
        )

    assert len(sent) == 2
    rows = _rows(refused.value)
    assert [row.param for row in rows] == [
        "MinPercentMinorAlleles",
        "ReadFrequencyPercent",
        "snp_class",
    ]
    assert rows[0].candidates is None
    for row, phrase in zip(rows[1:], ["95 percent", "non-synonymous"], strict=True):
        assert row.candidates is not None
        assert [c.value for c in row.candidates] == _led(options[row.param], phrase)


def _both() -> list[WDKParameter]:
    return [*variant_characteristics(), *_interpro()]


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
async def test_an_early_miss_and_a_later_entry_are_one_refusal() -> None:
    with pytest.raises(ValidationError) as refused:
        await read_under_parents(
            serving(*_both()), _A_MISS_THEN_AN_ENTRY, _reads(), about=None
        )

    assert not isinstance(refused.value, VocabularyEntryError)
    assert [row.param for row in _rows(refused.value)] == [
        "gene_variant_stats",
        "domain_typeahead",
    ]


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
async def test_the_walk_names_an_early_miss_and_a_later_entry_at_once() -> None:
    with pytest.raises(ValidationError) as refused:
        await resolve_params_with_intent(
            fetch_at=serving(*_both()),
            filter_reads=_reads(),
            intent=ParamIntent(),
            search=SearchContext("plasmodb", "transcript", "GenesByInterproDomain"),
            stated=_A_MISS_THEN_AN_ENTRY,
            about=None,
        )

    assert [row.param for row in _rows(refused.value)] == [
        "gene_variant_stats",
        "domain_typeahead",
    ]


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
async def test_a_refused_parent_skips_only_its_own_subtree() -> None:
    stated: dict[str, JsonValue] = {
        **_A_MISS_THEN_AN_ENTRY,
        "domain_database": "no such database",
    }

    with pytest.raises(ValidationError) as refused:
        await read_under_parents(serving(*_both()), stated, _reads(), about=None)

    assert [row.param for row in _rows(refused.value)] == [
        "gene_variant_stats",
        "domain_database",
    ]
