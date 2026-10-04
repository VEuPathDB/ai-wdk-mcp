"""The phrasings one vocabulary lookup reads, and the entries each one matches.

Pure module (no I/O). A term matches as a phrase with hyphen and space alike,
then as its words in any order, then by each uncommon word when neither matched.
The kept entries that carry the request's own words rank first.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import ConfigDict, Field
from veupathdb.domain.parameters import VocabOption
from veupathdb.model import CamelModel

Reach = Literal["phrase", "every_word", "word"]
_REACH_ORDER: tuple[Reach, ...] = ("phrase", "every_word", "word")
_WORD = re.compile(r"[^\W_]+")
_FEWEST_WORDS_TO_SPLIT = 2
# A word more than this share of the labels hold names no concept on its own.
_COMMON_WORD_SHARE = 0.1


def _folded(text: str) -> str:
    """The text in lower case, with every run of other characters one space."""
    return " ".join(_WORD.findall(text.casefold()))


class PhrasingMatch(CamelModel):
    """One phrasing a lookup read, and the entries it matched first."""

    model_config = ConfigDict(frozen=True)

    term: str
    phrasing: str
    reach: Reach
    values: list[str] = Field(default_factory=list)


class VocabLookup(CamelModel):
    """The terms a read narrowed a vocabulary by, and the phrasings that matched.

    Each kept entry is counted under the first phrasing that matched it.
    ``request_matches`` counts each kept entry that carries the request's own
    words under the first phrasing of those words that holds it.
    """

    model_config = ConfigDict(frozen=True)

    terms: list[str]
    matches: list[PhrasingMatch] = Field(default_factory=list)
    request_terms: list[str] = Field(default_factory=list)
    request_matches: list[PhrasingMatch] = Field(default_factory=list)

    def request_values(self) -> list[str]:
        """The kept entries that carry the request's words, in rank order."""
        return [value for match in self.request_matches for value in match.values]


@dataclass(frozen=True, slots=True)
class _Phrasing:
    term: str
    text: str
    reach: Reach

    def holds(self, *labels: str) -> bool:
        if self.reach == "every_word":
            words = self.text.split()
            return any(all(word in label for word in words) for label in labels)
        return any(self.text in label for label in labels)


def _phrasings_of(term: str, reach: Reach) -> list[_Phrasing]:
    text = _folded(term)
    words = text.split()
    if reach == "phrase":
        return [_Phrasing(term, text, "phrase")] if text else []
    if len(words) < _FEWEST_WORDS_TO_SPLIT:
        return []
    if reach == "every_word":
        return [_Phrasing(term, text, "every_word")]
    return [_Phrasing(term, word, "word") for word in dict.fromkeys(words)]


@dataclass(frozen=True, slots=True)
class VocabRead:
    """The entries a lookup kept, ranked, and the phrasings it applied."""

    options: list[VocabOption]
    lookup: VocabLookup | None
    phrasings: tuple[_Phrasing, ...] = ()

    def matches(self, value: str, display: str) -> bool:
        """Whether an entry holds any phrasing the lookup applied."""
        labels = (_folded(value), _folded(display))
        return any(phrasing.holds(*labels) for phrasing in self.phrasings)


_Labels = list[tuple[str, str]]


def _labels(options: list[VocabOption]) -> _Labels:
    return [(_folded(o.value), _folded(o.display)) for o in options]


def _applied(labels: _Labels, term: str) -> list[_Phrasing]:
    """The phrase and its words in any order, and each uncommon word alone when
    neither matches an entry. A word alone matches entries that hold less of the term."""
    whole = _phrasings_of(term, "phrase") + _phrasings_of(term, "every_word")
    if any(p.holds(*label) for p in whole for label in labels):
        return whole
    common = _COMMON_WORD_SHARE * len(labels)
    return whole + [
        word
        for word in _phrasings_of(term, "word")
        if sum(word.holds(*label) for label in labels) <= common
    ]


def _claimed(
    phrasings: Sequence[_Phrasing], options: list[VocabOption], labels: _Labels
) -> dict[_Phrasing, list[VocabOption]]:
    """Each option under the first phrasing that holds it, by reach."""
    ranked = sorted(phrasings, key=lambda p: _REACH_ORDER.index(p.reach))
    claimed: dict[_Phrasing, list[VocabOption]] = {p: [] for p in ranked}
    seen: set[str] = set()
    for phrasing in ranked:
        for option, label in zip(options, labels, strict=True):
            if option.value not in seen and phrasing.holds(*label):
                claimed[phrasing].append(option)
                seen.add(option.value)
    return claimed


def _matched(claimed: dict[_Phrasing, list[VocabOption]]) -> list[PhrasingMatch]:
    return [
        PhrasingMatch(
            term=p.term,
            phrasing=p.text,
            reach=p.reach,
            values=[option.value for option in options],
        )
        for p, options in claimed.items()
        if options
    ]


def read_options(
    options: list[VocabOption],
    terms: Sequence[str],
    *,
    request_terms: Sequence[str],
) -> VocabRead:
    """Keep the entries any phrasing of the terms matches, ranked by reach.

    ``request_terms`` are the concept in the request's own words. They are read
    as a term is, and the kept entries they match rank first. They keep no entry.
    """
    if not terms:
        return VocabRead(options=options, lookup=None)
    labels = _labels(options)
    phrasings = [p for term in terms for p in _applied(labels, term)]
    by_term = _claimed(phrasings, options, labels)
    kept = [option for claimed in by_term.values() for option in claimed]
    asked = [p for term in request_terms for p in _applied(labels, term)]
    by_request = _claimed(asked, kept, _labels(kept))
    first = [option for claimed in by_request.values() for option in claimed]
    carried = {option.value for option in first}
    return VocabRead(
        options=first + [option for option in kept if option.value not in carried],
        lookup=VocabLookup(
            terms=list(terms),
            matches=_matched(by_term),
            request_terms=list(request_terms),
            request_matches=_matched(by_request),
        ),
        phrasings=tuple(phrasings),
    )
