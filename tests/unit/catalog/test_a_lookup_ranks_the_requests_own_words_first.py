"""The kept entries that carry the request's own words rank first, phrase before
word, and a cut list says how many of them it holds."""

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
from veupathdb_mcp.catalog.vocab_lookup import PhrasingMatch, read_options

from .pfam_refresh import CONTEXT, DAL972, PARAMETER, SEARCH, serve

_OBP = VocabOption(
    value="IPR006170", display="Pheromone/general odorant binding protein domain"
)
_PBP_GOBP = VocabOption(value="PF01395", display="PBP/GOBP family")
_A10_OSD = VocabOption(
    value="PF03392", display="Insect pheromone-binding family, A10/OS-D"
)
_RECEPTOR = VocabOption(value="PF02949", display="7tm Odorant receptor")
_FILLERS = [
    VocabOption(value=f"PF9{index:04d}", display=display)
    for index, display in enumerate(
        (
            "Protein kinase domain",
            "Zinc finger, C2H2 type",
            "WD domain, G-beta repeat",
            "Ankyrin repeats",
            "ABC transporter",
            "Helicase conserved C-terminal domain",
            "RNA recognition motif",
            "Ras family",
            "Cytochrome P450",
            "Sugar transporter",
            "Thioredoxin",
            "Leucine Rich Repeat",
            "Tetratricopeptide repeat",
            "Methyltransferase domain",
            "Short chain dehydrogenase",
            "AAA domain",
        )
    )
]
_DOMAINS = [_OBP, _PBP_GOBP, _A10_OSD, _RECEPTOR, *_FILLERS]
_SYNONYMS_FIRST = ["insect pheromone-binding", "pheromone binding", "odorant"]
_REQUEST = "odorant-binding protein"


def _values(options: list[VocabOption] | None) -> list[str]:
    return [option.value for option in options or []]


def test_the_request_words_rank_their_entry_above_a_synonym_match() -> None:
    read = read_options(_DOMAINS, _SYNONYMS_FIRST, request_terms=[_REQUEST])

    assert _values(read.options) == ["IPR006170", "PF03392", "PF02949"]


def test_with_no_request_words_the_phrasings_rank_in_their_order() -> None:
    read = read_options(_DOMAINS, _SYNONYMS_FIRST, request_terms=[])

    assert _values(read.options) == ["PF03392", "IPR006170", "PF02949"]
    assert read.lookup is not None
    assert read.lookup.request_terms == []
    assert read.lookup.request_matches == []


def test_a_request_phrase_ranks_before_a_request_word() -> None:
    read = read_options(
        _DOMAINS,
        _SYNONYMS_FIRST,
        request_terms=[_REQUEST, "olfactory odorant receptor"],
    )

    assert _values(read.options) == ["IPR006170", "PF02949", "PF03392"]
    assert read.lookup is not None
    assert read.lookup.request_matches == [
        PhrasingMatch(
            term=_REQUEST,
            phrasing="odorant binding protein",
            reach="phrase",
            values=["IPR006170"],
        ),
        PhrasingMatch(
            term="olfactory odorant receptor",
            phrasing="odorant",
            reach="word",
            values=["PF02949"],
        ),
    ]


def test_the_request_words_rank_and_the_phrasings_keep() -> None:
    """An entry no phrasing matches stays out, whatever words it carries."""
    read = read_options(
        [*_DOMAINS, VocabOption(value="PF9999", display="Odorant binding protein 56a")],
        ["pheromone binding"],
        request_terms=[_REQUEST],
    )

    assert _values(read.options) == ["IPR006170", "PF03392"]
    assert read.lookup is not None
    assert read.lookup.terms == ["pheromone binding"]
    assert read.lookup.request_terms == [_REQUEST]
    assert read.lookup.request_values() == ["IPR006170"]


def test_each_entry_is_still_counted_under_the_phrasing_that_matched_it() -> None:
    read = read_options(
        _DOMAINS,
        [_REQUEST, "pheromone binding", "insect pheromone-binding"],
        request_terms=[_REQUEST],
    )

    assert _values(read.options) == ["IPR006170", "PF03392"]
    assert read.lookup is not None
    assert [(m.term, m.reach, m.values) for m in read.lookup.matches] == [
        (_REQUEST, "phrase", ["IPR006170"]),
        ("pheromone binding", "phrase", ["PF03392"]),
    ]


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
        "entries whose labels carry the request's words 'RNA-binding', first."
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
