"""The parameter sheet a model reads before it proposes values for a search."""

from __future__ import annotations

import re

from pydantic import Field
from veupathdb.domain.parameters.wdk_vocab import (
    VocabOption,
    leading_accession_token,
)
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.param_formatting import FilterFieldInfo, ParameterInfo

# Below this, the whole vocabulary is cheap enough to send and ranking can only
# lose information. 200 options is roughly 4K tokens.
DIRECT_MAX = 200
# The shortlist a large vocabulary is reduced to. Same order as DIRECT_MAX so the
# model sees a comparable amount either way.
TOP_K = 200

_WORD = re.compile(r"[a-z0-9]+")
# An accession carries inner punctuation, so it is read as one token.
_TOKEN = re.compile(r"[a-z0-9][a-z0-9:._-]*")
# Shorter words match everything and rank nothing.
_MIN_WORD_LENGTH = 3
# Long enough to survive the length filter, but they say nothing about a label.
_STOPWORDS = frozenset(
    {
        "the",
        "not",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "are",
        "all",
        "any",
        "but",
        "its",
        "per",
        "via",
    }
)


class SheetEntry(CamelModel):
    """One visible parameter with everything needed to propose a value for it."""

    name: str
    display_name: str
    type: str
    required: bool
    is_number: bool = False
    is_tree: bool = False
    help: str = ""
    default: str | None = None
    min: float | None = None
    max: float | None = None
    depends_on: list[str] = Field(default_factory=list)
    vocabulary: list[VocabOption] = Field(default_factory=list)
    vocabulary_total: int = 0
    vocabulary_note: str | None = None
    filter_facets: list[FilterFieldInfo] = Field(default_factory=list)


def _query_words(query: str) -> list[str]:
    return [
        w
        for w in _WORD.findall(query.casefold())
        if len(w) >= _MIN_WORD_LENGTH and w not in _STOPWORDS
    ]


def _query_tokens(query: str) -> frozenset[str]:
    """The request's words, each kept whole so an accession survives punctuation."""
    return frozenset(token.rstrip(":._-") for token in _TOKEN.findall(query.casefold()))


def _is_named(option: VocabOption, query: str, tokens: frozenset[str]) -> bool:
    """The request writes this option out: its value, its label, or its accession.

    An identifier the user wrote is not a similarity question. It must reach the
    model even when nothing else about the option matches the request.
    """
    if option.value and option.value.casefold() in query:
        return True
    if option.display and option.display.casefold() in query:
        return True
    accession = leading_accession_token(option.value)
    return accession is not None and accession.casefold() in tokens


def _label_words(option: VocabOption) -> frozenset[str]:
    """The words of a label. A request word matches a whole word, not a fragment."""
    return frozenset(_WORD.findall((option.display or option.value).casefold()))


def _word_weights(labels: list[frozenset[str]], words: list[str]) -> dict[str, float]:
    """The weight of each request word: the rarer it is here, the more it is worth.

    A word ``n`` labels hold is worth ``1/n``, so a word one label holds is worth
    1.0, the most any single word can be worth. It outweighs one common word, not
    an unbounded number of them: a label that matches three words of weight 0.5
    scores higher.
    """
    frequencies = {word: sum(word in label for label in labels) for word in words}
    return {word: 1.0 / count for word, count in frequencies.items() if count}


def _rarity_score(label: frozenset[str], weights: dict[str, float]) -> float:
    return sum(weight for word, weight in weights.items() if word in label)


def _shortlist(options: list[VocabOption], query: str) -> list[VocabOption]:
    """The ``TOP_K`` options whose labels hold the rarest words of the request."""
    low = query.casefold()
    words = _query_words(low)
    tokens = _query_tokens(low)
    labels = [_label_words(option) for option in options]
    weights = _word_weights(labels, words)
    ranked = sorted(
        enumerate(options),
        key=lambda pair: (
            not _is_named(pair[1], low, tokens),
            -_rarity_score(labels[pair[0]], weights),
            pair[0],
        ),
    )
    return [option for _, option in ranked[:TOP_K]]


def _note(info: ParameterInfo, shown: int, total: int) -> str | None:
    parts: list[str] = []
    # An empty vocabulary offers nothing, so its note is the reason it is empty.
    if not shown and info.allowed_values_note:
        parts.append(info.allowed_values_note)
    if total > shown:
        parts.append(
            f"{total} values; the {shown} most relevant to the request by name are "
            f"shown. If the value you need is absent, call get_parameter_options("
            f"search_name, '{info.name}', query='<keyword>') before deciding it does not exist."
        )
    if info.allowed_values_tree is not None:
        parts.append("A parent term selects all of its children.")
    if info.vocab_depends_on:
        parents = ", ".join(info.vocab_depends_on)
        parts.append(
            f"This vocabulary depends on {parents} and is shown under the search defaults; "
            f"it is re-read under the values you propose."
        )
    return " ".join(parts) or None


def build_sheet(infos: list[ParameterInfo], *, query: str) -> list[SheetEntry]:
    """Visible parameters only. A vocabulary over ``DIRECT_MAX`` is shortlisted."""
    entries: list[SheetEntry] = []
    for info in infos:
        if not info.is_visible:
            continue
        options = info.vocabulary()
        shown = options if len(options) <= DIRECT_MAX else _shortlist(options, query)
        entries.append(
            SheetEntry(
                name=info.name,
                display_name=info.display_name,
                type=info.type,
                required=info.required,
                is_number=info.is_number,
                is_tree=info.allowed_values_tree is not None,
                help=info.help,
                default=info.default_value,
                min=info.min,
                max=info.max,
                depends_on=list(info.vocab_depends_on or []),
                vocabulary=shown,
                vocabulary_total=len(options),
                vocabulary_note=_note(info, len(shown), len(options)),
                filter_facets=info.filter_fields,
            )
        )
    return entries
