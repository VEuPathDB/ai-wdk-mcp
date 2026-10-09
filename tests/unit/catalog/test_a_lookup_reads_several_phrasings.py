"""A vocabulary lookup for a concept reads several phrasings of it, merges the
entries they match, ranks them, and names each phrasing that matched."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters import VocabOption
from veupathdb.testing import NEEDS_QA_RECORDING

from veupathdb_mcp.catalog.param_formatting import ParameterInfo
from veupathdb_mcp.catalog.search_inspection import (
    VocabNarrowing,
    read_parameter_options,
)

from .pfam_refresh import CONTEXT, DAL972, PARAMETER, SEARCH, serve

pytestmark = pytest.mark.skip(reason=NEEDS_QA_RECORDING)

# Labels that hold "RNA-binding" with a hyphen, which one substring missed.
_HYPHENATED = ("PF14608", "PF12171")
_RRM = ("PF00076", "PF13893")
_KH = "PF00013"


async def _read(query: str | list[str]) -> ParameterInfo:
    result = await read_parameter_options(
        "tritrypdb",
        SEARCH,
        PARAMETER,
        record_type="transcript",
        context_values=CONTEXT,
        narrowing=VocabNarrowing(query=query),
    )
    assert result.kind == "parameter_info"
    return result


def _values(options: list[VocabOption] | None) -> list[str]:
    return [option.value for option in options or []]


async def test_hyphen_and_space_read_alike(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, DAL972)

    spaced = await _read("RNA binding")
    hyphenated = await _read("RNA-binding")

    assert set(_HYPHENATED) <= set(_values(spaced.allowed_values))
    assert _values(spaced.allowed_values) == _values(hyphenated.allowed_values)


async def test_the_words_in_another_order_rank_after_the_phrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, DAL972)

    info = await _read("RNA binding")

    lookup = info.vocab_lookup
    assert lookup is not None
    assert [(m.phrasing, m.reach) for m in lookup.matches] == [
        ("rna binding", "phrase"),
        ("rna binding", "every_word"),
    ]
    phrase, every_word = lookup.matches
    assert len(phrase.values) == 24
    assert len(every_word.values) == 6
    assert _values(info.allowed_values) == phrase.values + every_word.values


async def test_several_phrasings_of_one_concept_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, DAL972)

    info = await _read(["RNA binding", "RNA recognition", "KH"])

    shown = _values(info.allowed_values)
    assert {*_HYPHENATED, *_RRM, _KH} <= set(shown)
    assert len(shown) == len(set(shown))
    lookup = info.vocab_lookup
    assert lookup is not None
    assert lookup.terms == ["RNA binding", "RNA recognition", "KH"]
    assert {m.term for m in lookup.matches} == set(lookup.terms)
    assert sum(len(m.values) for m in lookup.matches) == len(shown)


async def test_the_words_alone_are_read_when_nothing_else_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, DAL972)

    info = await _read("recognition helicase")

    lookup = info.vocab_lookup
    assert lookup is not None
    assert [(m.phrasing, m.reach, len(m.values)) for m in lookup.matches] == [
        ("recognition", "word", 7),
        ("helicase", "word", 20),
    ]
    assert set(_RRM) <= set(_values(info.allowed_values))


async def test_a_word_most_labels_hold_is_not_read_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """451 of the 2441 labels hold "protein", so it names no concept alone."""
    serve(monkeypatch, DAL972)

    info = await _read("RNA recognition protein")

    lookup = info.vocab_lookup
    assert lookup is not None
    assert [m.phrasing for m in lookup.matches] == ["rna", "recognition"]


async def test_a_phrase_that_matches_keeps_its_words_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A word alone would pull in every entry that holds "rna"."""
    serve(monkeypatch, DAL972)

    info = await _read("RNA binding")

    assert not set(_RRM) & set(_values(info.allowed_values))
