"""The values a model reads of a long vocabulary: the ones the request names best."""

from __future__ import annotations

import re

from veupathdb.domain.parameters import (
    UnboundParameter,
    VocabOption,
    leading_accession_token,
)

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


def shortlist(options: list[VocabOption], query: str) -> list[VocabOption]:
    """The options a model reads: all of them up to ``DIRECT_MAX``, else the
    ``TOP_K`` whose labels hold the rarest words of the request."""
    if len(options) <= DIRECT_MAX:
        return options
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


def shortlist_values(values: list[str], query: str) -> list[str]:
    """``shortlist`` over plain values, each its own label."""
    shown = shortlist([VocabOption(value=v, display=v) for v in values], query)
    return [option.value for option in shown]


def shortlist_slot[Slot: UnboundParameter](slot: Slot, query: str) -> Slot:
    """The open slot as a model reads it. A cut slot names its total in its question."""
    shown = shortlist_values(slot.options, query)
    if len(shown) == len(slot.options):
        return slot
    note = (
        f"{len(slot.options)} values; the {len(shown)} the request names best are "
        f"listed. get_parameter_options with query='<words>' reads the values the "
        f"cut left out."
    )
    return slot.model_copy(
        update={"options": shown, "question": f"{slot.question} ({note})"}
    )
