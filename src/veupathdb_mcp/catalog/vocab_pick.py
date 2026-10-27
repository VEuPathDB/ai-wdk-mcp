"""The vocabulary entry a Decisions choice picks for a requirement, and how sure it is.

A Choice over the entries a lookup kept, plus "none fits", picks one entry. A
predicate over the picked entry then asks whether it states the requirement. The
pick's confidence is the lower of the two.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ConfigDict
from veupathdb.domain.parameters import VocabOption
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.decisions import (
    MAX_CHOICES,
    Choice,
    ChoiceQuestion,
    DecisionRequest,
    PredicateQuestion,
    decide,
)
from veupathdb_mcp.computed import computed
from veupathdb_mcp.settings import get_mcp_settings

NONE_FITS = "none_fits"
_CHOICE = "value"
_FIT = "fits"
_NONE_FITS_TEXT = (
    "None of these values states the requirement: each is obsolete, broader, "
    "narrower or about something else."
)
_CHOICE_TEXT = (
    "Which parameter value states the requirement? Read each label; choose "
    "none_fits when no value states it."
)
_FIT_TEXT = (
    "The proposed value states the requirement: it is a current entry, not "
    "obsolete, and it is neither broader, narrower nor about something else."
)


class VocabPick(CamelModel):
    """The entry a Decisions choice picked among the entries a lookup kept.

    ``value`` is None when the choice answered that no offered entry states the
    requirement. A pick that is not ``settled`` is a question for the researcher.
    """

    model_config = ConfigDict(frozen=True)

    value: str | None = None
    display: str | None = None
    choice_confidence: float
    fit_probability: float | None = None
    min_confidence: float
    offered: int

    @computed
    def confidence(self) -> float:
        if self.fit_probability is None:
            return self.choice_confidence
        return min(self.choice_confidence, self.fit_probability)

    @computed
    def settled(self) -> bool:
        return self.value is not None and self.confidence >= self.min_confidence


def _state(site_id: str, parameter: str, requirement: str) -> str:
    return (
        f"VEuPathDB site: {site_id}. Parameter: {parameter}.\n"
        f"Researcher's requirement: {requirement}"
    )


def choice_request(
    site_id: str, parameter: str, requirement: str, entries: Sequence[VocabOption]
) -> DecisionRequest:
    """One Choice over the first entries that fit, plus none_fits."""
    offered = entries[: MAX_CHOICES - 1]
    choices = [
        Choice(value=f"e{i}", description=entry.display)
        for i, entry in enumerate(offered)
    ]
    return DecisionRequest(
        input=_state(site_id, parameter, requirement),
        questions=[
            ChoiceQuestion(
                name=_CHOICE,
                instructions=_CHOICE_TEXT,
                choices=[
                    *choices,
                    Choice(value=NONE_FITS, description=_NONE_FITS_TEXT),
                ],
            )
        ],
    )


def fit_request(
    site_id: str, parameter: str, requirement: str, entry: VocabOption
) -> DecisionRequest:
    """One predicate: whether the picked entry states the requirement."""
    return DecisionRequest(
        input=f"{_state(site_id, parameter, requirement)}\nProposed value: {entry.display}",
        questions=[PredicateQuestion(name=_FIT, instructions=_FIT_TEXT)],
    )


async def pick_vocab_entry(
    site_id: str, parameter: str, requirement: str, entries: Sequence[VocabOption]
) -> VocabPick | None:
    """The entry that states the requirement, or None when the service answers
    neither the choice nor the fit."""
    if not entries or not requirement.strip():
        return None
    request = choice_request(site_id, parameter, requirement, entries)
    response = await decide(request, purpose="vocabulary pick")
    answer = None if response is None else response.choice(_CHOICE)
    if answer is None:
        return None
    floor = get_mcp_settings().decisions_vocab_min_confidence
    offered = min(len(entries), MAX_CHOICES - 1)
    if answer.choice == NONE_FITS:
        return VocabPick(
            choice_confidence=answer.confidence, min_confidence=floor, offered=offered
        )
    entry = entries[int(answer.choice.removeprefix("e"))]
    fit = await decide(
        fit_request(site_id, parameter, requirement, entry), purpose="vocabulary fit"
    )
    judged = None if fit is None else fit.predicate(_FIT)
    if judged is None:
        return None
    return VocabPick(
        value=entry.value,
        display=entry.display,
        choice_confidence=answer.confidence,
        fit_probability=judged.probability,
        min_confidence=floor,
        offered=offered,
    )
