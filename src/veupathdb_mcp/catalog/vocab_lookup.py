"""The phrasings one vocabulary lookup reads, and the entries each one matches.

Pure module (no I/O). A term matches as a phrase with hyphen and space alike,
then as its words in any order, then by each uncommon word when neither matched.
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
    """

    model_config = ConfigDict(frozen=True)

    terms: list[str]
    matches: list[PhrasingMatch] = Field(default_factory=list)


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


def read_options(options: list[VocabOption], terms: Sequence[str]) -> VocabRead:
    """Keep the entries any phrasing of the terms matches, ranked by reach."""
    if not terms:
        return VocabRead(options=options, lookup=None)
    labels = _labels(options)
    phrasings = [p for term in terms for p in _applied(labels, term)]
    ranked = sorted(phrasings, key=lambda p: _REACH_ORDER.index(p.reach))
    claimed: dict[_Phrasing, list[VocabOption]] = {p: [] for p in ranked}
    seen: set[str] = set()
    for phrasing in ranked:
        for option, label in zip(options, labels, strict=True):
            if option.value not in seen and phrasing.holds(*label):
                claimed[phrasing].append(option)
                seen.add(option.value)
    return VocabRead(
        options=[option for p in ranked for option in claimed[p]],
        lookup=VocabLookup(
            terms=list(terms),
            matches=[
                PhrasingMatch(
                    term=p.term,
                    phrasing=p.text,
                    reach=p.reach,
                    values=[option.value for option in claimed[p]],
                )
                for p in ranked
                if claimed[p]
            ],
        ),
        phrasings=tuple(phrasings),
    )
