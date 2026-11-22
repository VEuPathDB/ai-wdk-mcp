"""The order a refusal shows its candidates in: the entry a Decisions choice picks first, never bound."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import NoReturn

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    model_validator,
)
from veupathdb import JSONArray
from veupathdb.domain.parameters import (
    DECIDED_CANDIDATES,
    SHOWN_CANDIDATES,
    Resolution,
    VocabOption,
    VocabularyEntryError,
    flatten_vocab,
    rank_entries,
)
from veupathdb.errors import ValidationError
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


async def _ordered_entries(
    about: ResolveContext, vocabulary: NamedVocabulary, phrase: str
) -> list[VocabOption]:
    ranked = rank_entries(vocabulary.options, phrase, DECIDED_CANDIDATES)
    if not ranked:
        return []
    request = resolve_request(about, vocabulary.display, phrase, ranked)
    response = await decide(request, purpose="vocabulary order")
    answer = None if response is None else response.choice(_ENTRY)
    pick = None if answer is None else _picked(answer.choice, ranked)
    if pick is None:
        return ranked[:SHOWN_CANDIDATES]
    shown = [pick, *(c for c in ranked if c.value != pick.value)]
    return shown[:SHOWN_CANDIDATES]


def interleaved[T](
    groups: Sequence[Sequence[T]], key: Callable[[T], str], limit: int
) -> list[T]:
    found: dict[str, T] = {}
    for rank in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if rank < len(group):
                found.setdefault(key(group[rank]), group[rank])
    return list(found.values())[:limit]


async def ordered_terms(
    about: ResolveContext, asked: Sequence[tuple[NamedVocabulary, str]]
) -> list[list[VocabOption]]:
    """For each (vocabulary, phrase), the first entries ``rank_entries`` ranks, led
    by the entry a Decisions choice picks among them when it picks one.

    Only the first ``SHOWN_CANDIDATES`` phrases ask a choice, all at once; every
    later phrase keeps the ranking, so one refusal sends a bounded number of calls.
    """
    asking = asked[:SHOWN_CANDIDATES]
    led = await asyncio.gather(*(_ordered_entries(about, v, p) for v, p in asking))
    kept = [
        rank_entries(v.options, p, SHOWN_CANDIDATES)
        for v, p in asked[SHOWN_CANDIDATES:]
    ]
    return [*led, *kept]


async def ordered_by_vocabulary(
    refusal: VocabularyEntryError,
    vocabularies: dict[str, NamedVocabulary],
    about: ResolveContext,
) -> VocabularyEntryError:
    """The same refusal, the candidates of its first faults led by the entry a
    Decisions choice picks (``ordered_terms``). With no pick, a fault keeps the
    ranking it holds."""
    open_faults = [
        (index, vocabularies[name], resolution)
        for index, (name, resolution) in enumerate(refusal.faults)
        if name in vocabularies and resolution.how == "unsettled"
    ]
    shown = await ordered_terms(about, [(v, r.phrase) for _, v, r in open_faults])
    faults = list(refusal.faults)
    for (index, _, resolution), entries in zip(open_faults, shown, strict=True):
        if entries:
            faults[index] = (
                faults[index][0],
                Resolution(
                    phrase=resolution.phrase, how="unsettled", candidates=entries
                ),
            )
    return VocabularyEntryError(faults)


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


class _RefusalRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    param: str | None = None
    detail: str | None = None
    message: str | None = None
    messages: list[str] = Field(default_factory=list)
    value: JsonValue = None
    candidates: list[VocabOption] | None = None

    @model_validator(mode="before")
    @classmethod
    def _a_row_that_is_not_an_object_is_its_detail(cls, value: object) -> object:
        return value if isinstance(value, Mapping) else {"detail": str(value)}

    def line(self) -> str:
        return self.detail or self.message or " ".join(self.messages)

    def fault(self) -> tuple[str, Resolution] | None:
        if self.candidates is None or self.param is None:
            return None
        return self.param, Resolution(
            phrase=str(self.value),
            how="unsettled" if self.candidates else "none",
            candidates=self.candidates,
        )


_ROWS: TypeAdapter[list[_RefusalRow]] = TypeAdapter(list[_RefusalRow])


def refused_names(refusal: ValidationError) -> set[str]:
    return {
        row.param
        for row in _ROWS.validate_python(refusal.errors or [])
        if row.param is not None
    }


def _from_rows(title: str, rows: JSONArray) -> ValidationError:
    parsed = _ROWS.validate_python(rows)
    faults = [fault for row in parsed if (fault := row.fault()) is not None]
    if faults and len(faults) == len(parsed):
        return VocabularyEntryError(faults)
    return ValidationError(
        title=title, detail="\n".join(row.line() for row in parsed), errors=rows
    )


def gathered(
    refusals: Sequence[ValidationError], order: Sequence[str]
) -> ValidationError:
    position = {name: index for index, name in enumerate(order)}
    rows: JSONArray = [row for refusal in refusals for row in refusal.errors or []]
    parsed = _ROWS.validate_python(rows)
    ranked = sorted(
        range(len(rows)),
        key=lambda index: position.get(parsed[index].param or "", len(position)),
    )
    in_order = [rows[index] for index in ranked]
    if len(refusals) == 1 and in_order == rows:
        return refusals[0]
    title = refusals[0].title if len(refusals) == 1 else "Invalid parameter values"
    return _from_rows(title, in_order)


async def ordered(
    refusal: ValidationError,
    declarations: Sequence[WDKParameter],
    about: ResolveContext | None,
) -> ValidationError:
    rows = refusal.errors or []
    found = [row.fault() for row in _ROWS.validate_python(rows)]
    faults = [fault for fault in found if fault is not None]
    if not faults:
        return refusal
    entries = VocabularyEntryError(faults)
    if about is not None:
        entries = await ordered_refusal(entries, declarations, about)
    shown = iter(entries.errors or [])
    return _from_rows(
        refusal.title,
        [
            held if fault is None else next(shown)
            for fault, held in zip(found, rows, strict=True)
        ],
    )


async def refuse_ordered(
    refusal: ValidationError,
    declarations: Sequence[WDKParameter],
    about: ResolveContext | None,
) -> NoReturn:
    shown = await ordered(refusal, declarations, about)
    if shown is refusal:
        raise refusal
    raise shown from refusal
