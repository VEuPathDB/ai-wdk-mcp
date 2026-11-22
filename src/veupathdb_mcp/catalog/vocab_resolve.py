"""The order a refusal shows its candidates in: the entry a Decisions choice picks first, never bound."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from pydantic import ConfigDict
from veupathdb.domain.parameters import (
    DECIDED_CANDIDATES,
    SHOWN_CANDIDATES,
    Resolution,
    VocabOption,
    VocabularyEntryError,
    flatten_vocab,
    rank_entries,
)
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog.decisions import (
    Choice,
    ChoiceQuestion,
    DecisionRequest,
    decide,
)

NONE_FITS = "none_fits"
_ENTRY = "value"
_CHOICE_TEXT = (
    "Which entry of the parameter do the researcher's words name? Read each "
    "label. Choose none_fits when the words name a group, several entries "
    "without choosing one, or nothing listed."
)
_NONE_FITS_TEXT = (
    "The words name no one of these entries: they name a group, several "
    "entries without choosing one, or nothing listed; or each entry is "
    "obsolete, broader, narrower or about something else."
)


class ResolveContext(CamelModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    message: str = ""


class NamedVocabulary(CamelModel):
    model_config = ConfigDict(frozen=True)

    display: str
    options: list[VocabOption]


def _input(about: ResolveContext, parameter: str, phrase: str) -> str:
    lines = [
        f"VEuPathDB site: {about.site_id}. Parameter: {parameter}.",
        f'The researcher\'s words: "{phrase}"',
    ]
    if about.message:
        lines.append(f"The researcher's message: {about.message}")
    return "\n".join(lines)


def resolve_request(
    about: ResolveContext,
    parameter: str,
    phrase: str,
    candidates: Sequence[VocabOption],
) -> DecisionRequest:
    return DecisionRequest(
        input=_input(about, parameter, phrase),
        questions=[
            ChoiceQuestion(
                name=_ENTRY,
                instructions=_CHOICE_TEXT,
                choices=[
                    *(
                        Choice(value=f"e{i}", description=entry.display)
                        for i, entry in enumerate(candidates)
                    ),
                    Choice(value=NONE_FITS, description=_NONE_FITS_TEXT),
                ],
            )
        ],
    )


def _picked(choice: str, ranked: Sequence[VocabOption]) -> VocabOption | None:
    index = choice.removeprefix("e")
    if choice == index or not index.isdigit() or int(index) >= len(ranked):
        return None
    return ranked[int(index)]


async def _ordered(
    about: ResolveContext, vocabulary: NamedVocabulary, resolution: Resolution
) -> Resolution:
    ranked = rank_entries(vocabulary.options, resolution.phrase, DECIDED_CANDIDATES)
    if not ranked:
        return resolution
    request = resolve_request(about, vocabulary.display, resolution.phrase, ranked)
    response = await decide(request, purpose="vocabulary order")
    answer = None if response is None else response.choice(_ENTRY)
    pick = None if answer is None else _picked(answer.choice, ranked)
    if pick is None:
        return resolution
    shown = [pick, *(c for c in ranked if c.value != pick.value)]
    return Resolution(
        phrase=resolution.phrase,
        how="unsettled",
        candidates=shown[:SHOWN_CANDIDATES],
    )


async def ordered_by_vocabulary(
    refusal: VocabularyEntryError,
    vocabularies: dict[str, NamedVocabulary],
    about: ResolveContext,
) -> VocabularyEntryError:
    """The same refusal, each fault's candidates led by the entry a Decisions
    choice picks. With no pick, a fault keeps the ranking it holds."""

    async def fault(name: str, resolution: Resolution) -> tuple[str, Resolution]:
        vocabulary = vocabularies.get(name)
        if vocabulary is None or resolution.how != "unsettled":
            return name, resolution
        return name, await _ordered(about, vocabulary, resolution)

    faults = await asyncio.gather(*(fault(n, r) for n, r in refusal.faults))
    return VocabularyEntryError(list(faults))


async def ordered_refusal(
    refusal: VocabularyEntryError,
    declarations: Sequence[WDKParameter],
    about: ResolveContext,
) -> VocabularyEntryError:
    """``ordered_by_vocabulary`` over the declarations the refusal was read under."""
    vocabularies = {
        d.name: NamedVocabulary(
            display=d.display_name or d.name, options=flatten_vocab(d.vocabulary)
        )
        for d in declarations
    }
    return await ordered_by_vocabulary(refusal, vocabularies, about)
