"""Narrows a search's parameters with the values already bound to it."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from veupathdb import get_logger
from veupathdb.errors import ValidationError, VEuPathDBError
from veupathdb.wdk import VEuPathDBClient, WDKParameter, WDKSearchResponse

logger = get_logger(__name__)


_NOT_NARROWED = "not narrowed to your parent values"
_PHYLETIC_NOTE = (
    f"{_NOT_NARROWED}; the site does not narrow organism with a phyletic pattern"
)


class NarrowingFailed(BaseModel):
    """The site did not answer the read under a context."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    published: WDKSearchResponse
    refusal: VEuPathDBError[StrEnum]

    @property
    def note(self) -> str:
        return f"{_NOT_NARROWED}; the site did not answer the read (HTTP {self.refusal.status})"


class NarrowingUnsupported(BaseModel):
    """The site does not narrow this context, so the read is not sent."""

    model_config = ConfigDict(frozen=True)

    published: WDKSearchResponse
    note: str


type NotNarrowed = NarrowingFailed | NarrowingUnsupported


class NarrowingUnsupportedError(ValidationError):
    def __init__(self, note: str) -> None:
        super().__init__(title="The site does not narrow these values", detail=note)


def narrowed_or_published(
    read: WDKSearchResponse | NotNarrowed, search_name: str
) -> WDKSearchResponse:
    """The narrowed view, or the published one where the site did not narrow."""
    match read:
        case NarrowingFailed() | NarrowingUnsupported():
            logger.warning(
                "search params not narrowed; using the static view",
                search=search_name,
                note=read.note,
            )
            return read.published
        case WDKSearchResponse():
            return read


def narrowed_or_raise(read: WDKSearchResponse | NotNarrowed) -> WDKSearchResponse:
    """The narrowed view; raises where the site did not narrow."""
    match read:
        case NarrowingFailed():
            raise read.refusal
        case NarrowingUnsupported():
            raise NarrowingUnsupportedError(read.note)
        case WDKSearchResponse():
            return read


def not_narrowed_note(read: WDKSearchResponse | NotNarrowed) -> str | None:
    """What a read from the published view states; None for a narrowed read."""
    match read:
        case NarrowingFailed() | NarrowingUnsupported():
            return read.note
        case WDKSearchResponse():
            return None


def _never_narrowed(search_name: str, context: dict[str, str]) -> str | None:
    """The measured contexts WDK refuses to narrow for any value."""
    if (
        search_name == "GenesByOrthologPattern"
        and context.get("organism", "[]") != "[]"
        and context.get("profile_pattern")
    ):
        return _PHYLETIC_NOTE
    return None


def context_for_metadata_read(
    context: dict[str, str],
    published: Sequence[WDKParameter] | None,
) -> dict[str, str]:
    """Adds the published default of every unset site-set parameter.

    WDK fills an omitted site-set value in the definition it returns, but its
    verdict still calls the omitted value missing. The published value travels
    with the read.
    """
    filled = dict(context)
    for spec in published or []:
        if spec.name in filled or spec.bindable or spec.initial_display_value is None:
            continue
        filled[spec.name] = spec.initial_display_value
    return filled


async def get_search_params_under_context(
    client: VEuPathDBClient,
    record_type: str,
    search_name: str,
    context: dict[str, str],
    *,
    published: WDKSearchResponse | None = None,
) -> WDKSearchResponse | NotNarrowed:
    """A search's parameters, narrowed by ``context``, or why WDK did not narrow
    them: the site failed, or the context is one WDK refuses for any value.

    ``published`` is the static view and supplies the parameter shape the read
    sends. A caller that holds a cached one passes it; otherwise this reads it,
    and raises when it is unreachable.
    """
    if published is None:
        published = await client.get_search_details(
            record_type, search_name, expand_params=True
        )
    if not context:
        return published
    never = _never_narrowed(search_name, context)
    if never is not None:
        return NarrowingUnsupported(published=published, note=never)
    try:
        return await client.get_search_details_with_params(
            record_type,
            search_name,
            context=context_for_metadata_read(
                context, published.search_data.parameters
            ),
            expand_params=True,
        )
    except VEuPathDBError as exc:
        return NarrowingFailed(published=published, refusal=exc)
