"""Narrows a search's parameters with the values already bound to it."""

from __future__ import annotations

from collections.abc import Sequence

from veupathdb import get_logger
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import VEuPathDBClient, WDKParameter, WDKSearchResponse

logger = get_logger(__name__)


def context_for_metadata_read(
    context: dict[str, str],
    published: Sequence[WDKParameter] | None,
) -> dict[str, str]:
    """Adds the published default of every unset hidden parameter.

    WDK builds a contextual definition from a whole parameter shape and judges
    it, so a hidden parameter the caller cannot state must travel at its
    published default or WDK reports it as missing.
    """
    filled = dict(context)
    for spec in published or []:
        if spec.name in filled or spec.is_visible or spec.initial_display_value is None:
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
) -> WDKSearchResponse:
    """A search's parameters, narrowed by ``context`` when WDK can narrow them.

    Narrowing replaces a dependent param's static vocabulary with the one valid
    under its parents. WDK can refuse to narrow a value it accepts on the run
    endpoint, so a refusal costs vocabulary precision and never the search.

    ``published`` is the static view. It supplies the parameter shape the read
    must send and the answer a refusal falls back to. A caller that holds a
    cached one passes it; otherwise this reads it, and raises when it is
    unreachable.
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
        logger.warning(
            "WDK could not contextualize search params; using the static view",
            search=search_name,
            record_type=record_type,
            context_params=sorted(context),
            error=str(exc),
        )
        return published
