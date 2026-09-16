"""A WDK refusal of a step that will not run, read into a sentence.

WDK reports the refusal as a validation bundle rendered inside its own prose,
nested once more for every input step it walks through.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum

import pydantic
from pydantic import ConfigDict, Field
from veupathdb.model import CamelModel

_MAX_NESTING = 8

_FIRST_OPERAND = "bq_left_op"
_SECOND_OPERAND = "bq_right_op"

# A value outside a parameter's vocabulary is the whole message WDK keys to it.
_REFUSED_VALUE = re.compile(r"Invalid value '(?P<value>.*)'\.", re.DOTALL)
# A dependent parameter repeats the fact and names the parameter at fault.
_REFUSED_DEPENDENCY = re.compile(
    r"(?P<parameter>[A-Za-z0-9_.-]+) => Invalid value '(?P<value>.*?)'\.",
    re.DOTALL,
)

# A term a researcher reads is short and holds no markup.
_MARKUP = frozenset("{}\\\n\r")
_MAX_TERM = 200

_UNREAD = (
    "This strategy cannot run. The site refused one of its steps and did not "
    "name the value at fault. Open the strategy and check its steps."
)
_MORE = " The site reported other problems as well."


class _StepPlace(StrEnum):
    """Which step of a strategy a refusal is about. The value is its phrase."""

    RUN = "the step you ran"
    FIRST_INPUT = "the first input of the step you ran"
    SECOND_INPUT = "the second input of the step you ran"
    EARLIER = "an earlier step in this strategy"


class _RunnableBundle(CamelModel):
    """The validation bundle WDK renders inside a refusal message.

    The three required fields keep a JSON object of another shape from being
    read as a bundle.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    keyed_errors: dict[str, list[str]]
    validation_level: str
    validation_status: str
    errors: list[str] = Field(default_factory=list)


class _RefusedValue(pydantic.BaseModel):
    """One parameter value the site refuses, and the step that holds it."""

    model_config = ConfigDict(frozen=True)

    place: _StepPlace
    parameter: str
    value: str


def _bundle_at(text: str, start: int) -> _RunnableBundle | None:
    try:
        raw, _ = json.JSONDecoder().raw_decode(text, start)
        return _RunnableBundle.model_validate(raw)
    except json.JSONDecodeError, pydantic.ValidationError:
        return None


def _embedded_bundle(text: str) -> _RunnableBundle | None:
    """The bundle a message carries inside its prose, if it carries one."""
    start = text.find("{")
    while start != -1:
        bundle = _bundle_at(text, start)
        if bundle is not None:
            return bundle
        start = text.find("{", start + 1)
    return None


def _place(chain: list[str]) -> _StepPlace:
    """Where a refusal sits, from the answer parameters walked to reach it."""
    if not chain:
        return _StepPlace.RUN
    if len(chain) > 1:
        return _StepPlace.EARLIER
    if chain[0].startswith(_FIRST_OPERAND):
        return _StepPlace.FIRST_INPUT
    if chain[0].startswith(_SECOND_OPERAND):
        return _StepPlace.SECOND_INPUT
    return _StepPlace.EARLIER


def _readable(term: str) -> bool:
    return 0 < len(term) <= _MAX_TERM and not _MARKUP.intersection(term)


def _refused(place: _StepPlace, parameter: str, value: str) -> list[_RefusedValue]:
    """One refused value, or nothing when the site names it in markup."""
    if not _readable(parameter) or not _readable(value):
        return []
    return [_RefusedValue(place=place, parameter=parameter, value=value)]


def _leaf_values(parameter: str, text: str, place: _StepPlace) -> list[_RefusedValue]:
    """The values one leaf message refuses, each under the parameter at fault."""
    direct = _REFUSED_VALUE.fullmatch(text.strip())
    if direct is not None:
        return _refused(place, parameter, direct["value"])
    return [
        one
        for found in _REFUSED_DEPENDENCY.finditer(text)
        for one in _refused(place, found["parameter"], found["value"])
    ]


def _collect(
    bundle: _RunnableBundle, chain: list[str], found: list[_RefusedValue]
) -> bool:
    """Collects the values one bundle refuses. True when a message is unread."""
    unread = bool(bundle.errors)
    for key, messages in bundle.keyed_errors.items():
        for text in messages:
            nested = _embedded_bundle(text)
            if nested is not None and len(chain) < _MAX_NESTING:
                unread |= _collect(nested, [*chain, key], found)
                continue
            values = _leaf_values(key, text, _place(chain))
            unread |= not values
            found.extend(values)
    return unread


def _sentence(found: list[_RefusedValue], *, unread: bool) -> str:
    if not found:
        return _UNREAD
    clauses = " ".join(
        f"{one.place.value.capitalize()} sets '{one.parameter}' to "
        f"'{one.value}', which the site no longer offers."
        for one in found
    )
    tail = (
        "Open that step and choose a value the site offers now."
        if len(found) == 1
        else "Open those steps and choose values the site offers now."
    )
    return f"This strategy cannot run. {clauses} {tail}{_MORE if unread else ''}"


def describe_step_refusal(message: str) -> str | None:
    """A sentence for a refusal of a step that will not run.

    Returns None when the message carries no validation bundle, so the caller
    keeps the text it already has.
    """
    bundle = _embedded_bundle(message)
    if bundle is None:
        return None
    found: list[_RefusedValue] = []
    unread = _collect(bundle, [], found)
    return _sentence(list(dict.fromkeys(found)), unread=unread)
