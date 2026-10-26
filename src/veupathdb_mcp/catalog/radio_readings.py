from collections.abc import Sequence
from typing import Literal

from veupathdb.domain.parameters import (
    MultiPickValue,
    ParamValue,
    SinglePickValue,
    StringValue,
)
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog.param_formatting import RADIO_OFF
from veupathdb_mcp.catalog.radio_pairs import RadioPair
from veupathdb_mcp.catalog.vocab_lookup import AccessionNames, read_options
from veupathdb_mcp.catalog.vocab_rendering import entries_of

_LABEL_REACH = frozenset({"phrase", "every_word"})
_MULTI_PICK = "multi-pick-vocabulary"


class LabelReading(CamelModel):
    kind: Literal["label"] = "label"
    parameter: str
    values: list[str]
    params: dict[str, ParamValue]


class DescriptionReading(CamelModel):
    kind: Literal["description"] = "description"
    parameter: str
    text: str
    params: dict[str, ParamValue]


class RadioReadings(CamelModel):
    pair: RadioPair
    term: str
    label_values: list[str]
    label: LabelReading | None = None
    description: DescriptionReading | None = None
    accession: AccessionNames | None = None


def _picked(param: WDKParameter, values: list[str]) -> ParamValue | None:
    if param.type == _MULTI_PICK:
        return MultiPickValue(values=values)
    return SinglePickValue(value=values[0]) if len(values) == 1 else None


def _readings(pair: RadioPair, vocabulary: WDKParameter, term: str) -> RadioReadings:
    options = entries_of(vocabulary.vocabulary)
    read = read_options(options, [term], request_terms=[])
    matches = [] if read.lookup is None else read.lookup.matches
    values = [
        value
        for match in matches
        if match.reach in _LABEL_REACH
        for value in match.values
        if value != RADIO_OFF
    ]
    picked = _picked(vocabulary, values) if values else None
    off = _picked(vocabulary, [RADIO_OFF])
    label = None
    if picked is not None:
        label = LabelReading(
            parameter=pair.vocabulary,
            values=values,
            params={
                pair.vocabulary: picked,
                pair.free_text: StringValue(value=RADIO_OFF),
            },
        )
    description = None
    if off is not None and any(option.value == RADIO_OFF for option in options):
        text = f"*{term.strip()}*"
        description = DescriptionReading(
            parameter=pair.free_text,
            text=text,
            params={pair.vocabulary: off, pair.free_text: StringValue(value=text)},
        )
    return RadioReadings(
        pair=pair,
        term=term,
        label_values=values,
        label=label,
        description=description,
        accession=None if read.lookup is None else read.lookup.accession,
    )


def radio_readings(
    pairs: Sequence[RadioPair], params: Sequence[WDKParameter], term: str
) -> list[RadioReadings]:
    by_name = {param.name: param for param in params}
    found: list[RadioReadings] = []
    for pair in pairs:
        vocabulary = by_name.get(pair.vocabulary)
        free_text = by_name.get(pair.free_text)
        if vocabulary is None or free_text is None:
            continue
        if not entries_of(vocabulary.vocabulary) or entries_of(free_text.vocabulary):
            continue
        found.append(_readings(pair, vocabulary, term))
    return found
