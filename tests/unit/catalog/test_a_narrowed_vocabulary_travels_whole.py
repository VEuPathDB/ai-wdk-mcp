"""A query-narrowed vocabulary travels whole, and a cut list names the total it was cut from."""

from __future__ import annotations

import pytest
from tests._support.recordings import TEST_ROOT
from veupathdb.domain.parameters import VocabOption
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKEnumParam

from veupathdb_mcp.catalog.param_formatting import (
    _MAX_NARROWED_ENTRIES,
    _MAX_VOCAB_ENTRIES,
    ParamDependencies,
    ParameterInfo,
    format_typed_param,
)
from veupathdb_mcp.catalog.search_inspection import (
    VocabNarrowing,
    read_parameter_options,
)
from veupathdb_mcp.catalog.vocab_lookup import VocabLookup

from .conftest import vocab_terms
from .pfam_refresh import CONTEXT, FOWLERI, PARAMETER, SEARCH, serve

# Four of the Pfam entries a 50-entry cut hid from the N. fowleri read.
_HIDDEN_BY_THE_OLD_CUT = ("PF13365", "PF02127", "PF00930", "PF03416")


async def _read(narrowing: VocabNarrowing | None = None) -> ParameterInfo:
    result = await read_parameter_options(
        "amoebadb",
        SEARCH,
        PARAMETER,
        record_type="transcript",
        context_values=CONTEXT,
        narrowing=narrowing,
    )
    assert result.kind == "parameter_info"
    return result


def _values(options: list[VocabOption] | None) -> set[str]:
    return {option.value for option in options or []}


@pytest.mark.skipif(
    needs_qa_recording(
        TEST_ROOT / "unit/catalog/fixtures/amoebadb_nfowleri_pfam_refresh.json"
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_every_peptidase_entry_travels(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, FOWLERI)

    info = await _read(VocabNarrowing(query="peptidase"))

    assert info.allowed_values is not None
    assert len(info.allowed_values) == 66
    assert set(_HIDDEN_BY_THE_OLD_CUT) <= _values(info.allowed_values)
    assert info.allowed_values_total is None
    assert info.allowed_values_note is None


@pytest.mark.skipif(
    needs_qa_recording(
        TEST_ROOT / "unit/catalog/fixtures/amoebadb_nfowleri_pfam_refresh.json"
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_an_unnarrowed_read_names_the_total_it_was_cut_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, FOWLERI)

    info = await _read()

    assert info.allowed_values is not None
    assert len(info.allowed_values) == _MAX_VOCAB_ENTRIES
    assert info.allowed_values_total == 3745
    assert info.allowed_values_note is not None
    assert f"{_MAX_VOCAB_ENTRIES} of 3745" in info.allowed_values_note


def test_a_narrowed_list_over_the_bound_says_n_of_m() -> None:
    size = _MAX_NARROWED_ENTRIES + 40
    param = WDKEnumParam(
        name="domain_typeahead",
        type="multi-pick-vocabulary",
        vocabulary=vocab_terms(
            *((f"PF{i:05d}", f"PF{i:05d} : Peptidase S{i}") for i in range(size))
        ),
    )

    info = format_typed_param(
        param,
        ParamDependencies(),
        lookup=VocabLookup(terms=["peptidase"]),
    )

    assert info.allowed_values is not None
    assert len(info.allowed_values) == _MAX_NARROWED_ENTRIES
    assert info.allowed_values_total == size
    assert info.allowed_values_note is not None
    assert f"{_MAX_NARROWED_ENTRIES} of {size}" in info.allowed_values_note
