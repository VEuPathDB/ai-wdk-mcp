"""The one resolver: the vocabulary entry a phrase names, under one of three arms."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import ConfigDict
from veupathdb.domain.parameters import (
    DECIDED_CANDIDATES,
    Resolution,
    VocabOption,
    exact_or_candidates,
)
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.decisions import (
    Choice,
    ChoiceQuestion,
    DecisionRequest,
    decide,
)
from veupathdb_mcp.catalog.vocab_pick import NONE_FITS, fit_request

type ResolveArm = Literal["refuse", "choice", "choice_fit"]

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


async def _fit(
    about: ResolveContext, parameter: str, phrase: str, entry: VocabOption
) -> float | None:
    request = fit_request(about.site_id, parameter, phrase, entry)
    response = await decide(request, purpose="vocabulary fit")
    judged = None if response is None else response.predicate(request.questions[0].name)
    return None if judged is None else judged.probability


async def resolve_entry(
    options: Sequence[VocabOption],
    phrase: str,
    *,
    parameter: str,
    about: ResolveContext,
    arm: ResolveArm,
    floor: float,
) -> Resolution:
    found = exact_or_candidates(options, phrase, DECIDED_CANDIDATES)
    if arm == "refuse" or found.how != "unsettled":
        return found
    request = resolve_request(about, parameter, phrase, found.candidates)
    response = await decide(request, purpose="vocabulary entry")
    answer = None if response is None else response.choice(_ENTRY)
    if answer is None or answer.choice == NONE_FITS:
        return found
    entry = found.candidates[int(answer.choice.removeprefix("e"))]
    confidence = answer.confidence
    if arm == "choice_fit":
        fit = await _fit(about, parameter, phrase, entry)
        if fit is None:
            return found
        confidence = min(confidence, fit)
    if confidence < floor:
        return Resolution(
            phrase=phrase,
            how="unsettled",
            candidates=found.candidates,
            confidence=confidence,
        )
    return Resolution(
        phrase=phrase,
        value=entry.value,
        display=entry.display,
        how="decided",
        candidates=found.candidates,
        confidence=confidence,
    )
