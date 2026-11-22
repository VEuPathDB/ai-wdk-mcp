"""A cut list holds every entry the request's own words name, first, and says so."""

from __future__ import annotations

import pytest
from tests._support.recordings import TEST_ROOT
from veupathdb.domain.parameters import VocabOption
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording

from veupathdb_mcp.catalog.param_formatting import ParameterInfo
from veupathdb_mcp.catalog.search_inspection import (
    VocabNarrowing,
    read_parameter_options,
)

from .pfam_refresh import CONTEXT, DAL972, PARAMETER, SEARCH, serve


def _values(options: list[VocabOption] | None) -> list[str]:
    return [option.value for option in options or []]


async def _read(narrowing: VocabNarrowing) -> ParameterInfo:
    result = await read_parameter_options(
        "tritrypdb",
        SEARCH,
        PARAMETER,
        record_type="transcript",
        context_values=CONTEXT,
        narrowing=narrowing,
    )
    assert result.kind == "parameter_info"
    return result


@pytest.mark.skipif(
    needs_qa_recording(
        TEST_ROOT / "unit/catalog/fixtures/tritrypdb_dal972_pfam_refresh.json"
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_a_cut_list_holds_every_entry_the_request_words_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The phrasing "protein" keeps 473 DAL972 entries, more than the cut shows."""
    serve(monkeypatch, DAL972)

    info = await _read(
        VocabNarrowing(query=["protein", "RNA binding"], request="RNA-binding")
    )

    lookup = info.vocab_lookup
    assert lookup is not None
    held = lookup.request_values()
    assert len(held) == 30
    assert _values(info.allowed_values)[:30] == held
    assert info.allowed_values_total == 496
    assert info.allowed_values_from_request == 30
    assert info.allowed_values_note == (
        "Showing 300 of 496 values (list truncated). Use the exact value/ID you "
        "need; it does not have to appear in this list. The list holds all 30 "
        "entries whose labels carry the request's words 'RNA-binding', first. "
        "93 of 2440 entries carry a name of one token past their accession, and 0 "
        "of them carry no name, so a lookup by name does not reach them. An entry "
        "no label names can still be on the site."
    )


@pytest.mark.skipif(
    needs_qa_recording(
        TEST_ROOT / "unit/catalog/fixtures/tritrypdb_dal972_pfam_refresh.json"
    ),
    reason=NEEDS_QA_RECORDING,
)
async def test_without_the_request_words_the_cut_hides_most_of_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ranked by the phrasings alone, the cut shows 6 of the 30 entries."""
    serve(monkeypatch, DAL972)

    whole = await _read(
        VocabNarrowing(query=["protein", "RNA binding"], request="RNA-binding")
    )
    plain = await _read(VocabNarrowing(query=["protein", "RNA binding"]))

    shown = set(_values(plain.allowed_values))
    assert whole.vocab_lookup is not None
    assert len([v for v in whole.vocab_lookup.request_values() if v in shown]) == 6
    assert plain.allowed_values_from_request is None
