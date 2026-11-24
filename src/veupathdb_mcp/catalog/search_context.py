"""Narrows a search's parameters with the values already bound to it."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from veupathdb import get_logger
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import VEuPathDBClient, WDKParameter, WDKSearchResponse

logger = get_logger(__name__)


class NotNarrowed(BaseModel):
    """WDK refused to narrow the parameters under a context."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    published: WDKSearchResponse
    refusal: VEuPathDBError[StrEnum]


def narrowed_or_published(
    read: WDKSearchResponse | NotNarrowed, search_name: str
) -> WDKSearchResponse:
    """The narrowed view, or the published one where WDK refused to narrow."""
    match read:
        case NotNarrowed():
            logger.warning(
                "WDK could not contextualize search params; using the static view",
                search=search_name,
                error=str(read.refusal),
            )
            return read.published
        case WDKSearchResponse():
            return read


def narrowed_or_raise(read: WDKSearchResponse | NotNarrowed) -> WDKSearchResponse:
    """The narrowed view; raises the site's refusal where WDK refused to narrow."""
    match read:
        case NotNarrowed():
            raise read.refusal
        case WDKSearchResponse():
            return read


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
    """A search's parameters, narrowed by ``context``, or the refusal when WDK
    does not narrow them.

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
        return NotNarrowed(published=published, refusal=exc)
