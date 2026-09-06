"""The parameter pairs one WDK query ORs, and the value that switches a half off."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field
from veupathdb.domain.parameters.wdk_vocab import (
    MAX_NEAREST_ENTRIES,
    nearest_entries,
)

from veupathdb_mcp.catalog.param_formatting import ParameterInfo

RADIO_OFF = "N/A"
"""The value a free-text half takes when it states nothing. An empty value is refused."""

_WILDCARD_CHARS = "*%"


class _SearchProperties(BaseModel):
    """The published property list that names the ORed halves."""

    model_config = ConfigDict(extra="ignore")
    radio_params: list[str] = Field(default_factory=list, alias="radio-params")


class RadioPair(BaseModel):
    """Two parameters one query ORs, so a value in either widens the search."""

    model_config = ConfigDict(frozen=True)
    vocabulary: str
    free_text: str


class RadioPairIssue(BaseModel):
    """A criterion written into the free-text half, and the entries nearest to it."""

    pair: RadioPair
    free_value: str
    nearest: list[str] = Field(default_factory=list)


def radio_pairs(properties: Mapping[str, list[str]]) -> list[RadioPair]:
    """The ORed pairs a search declares. The vocabulary half is named first."""
    names = _SearchProperties.model_validate(properties).radio_params
    return [
        RadioPair(vocabulary=names[i], free_text=names[i + 1])
        for i in range(0, len(names) - 1, 2)
    ]


def _stated(proposal: str | list[str] | None) -> str | None:
    """The criterion a free-text proposal states, or ``None`` for none.

    A blank value and the off value both state nothing.
    """
    values = [proposal] if isinstance(proposal, str) else proposal or []
    stated = [
        text
        for value in values
        if (text := value.strip()) and text.casefold() != RADIO_OFF.casefold()
    ]
    return stated[0] if stated else None


def _has_radio_shape(by_name: Mapping[str, ParameterInfo], pair: RadioPair) -> bool:
    """Whether the sheet shows the declared halves in the order the rule reads.

    The vocabulary half holds a vocabulary and the free-text half holds none. A
    declaration in any other shape states something this rule does not describe.
    """
    vocabulary = by_name.get(pair.vocabulary)
    free_text = by_name.get(pair.free_text)
    if vocabulary is None or free_text is None:
        return False
    return bool(vocabulary.vocabulary()) and not free_text.vocabulary()


def check_radio_pairs(
    pairs: Sequence[RadioPair],
    infos: list[ParameterInfo],
    proposals: Mapping[str, str | list[str] | None],
) -> tuple[dict[str, str], RadioPairIssue | None]:
    """The off value for every free-text half that states nothing, and the first
    half that states a criterion the vocabulary half must carry instead."""
    by_name = {info.name: info for info in infos}
    overrides: dict[str, str] = {}
    issue: RadioPairIssue | None = None
    for pair in pairs:
        if not _has_radio_shape(by_name, pair):
            continue
        value = _stated(proposals.get(pair.free_text))
        if value is None:
            overrides[pair.free_text] = RADIO_OFF
        elif issue is None:
            issue = RadioPairIssue(
                pair=pair,
                free_value=value,
                nearest=nearest_entries(
                    by_name[pair.vocabulary].vocabulary(),
                    value.strip(_WILDCARD_CHARS),
                    MAX_NEAREST_ENTRIES,
                ),
            )
    return overrides, issue
