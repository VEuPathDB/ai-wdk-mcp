"""The context a search-parameter validation failure reports."""

from veupathdb import get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.strategy import StepValidation
from veupathdb.errors import ValidationError, VEuPathDBError
from veupathdb.model import CamelModel
from veupathdb.wdk import bundle_rows

from veupathdb_mcp.catalog.discovery_service import DiscoveryService

logger = get_logger(__name__)


class _UnreadableSearchContext(CamelModel):
    """The record type whose catalog is offered when a search does not load."""

    record_type: str
    available_searches: list[str]
    record_type_hint: str | None = None


def unknown_search_error(
    *, search_name: str, record_type: str | None, record_type_hint: str | None
) -> ValidationError:
    """No record type on the site publishes this search."""
    return ValidationError(
        title=f"Unknown or invalid search: {search_name}",
        detail="Search name not found in any record type.",
        errors=[
            {"context": {"recordType": record_type, "recordTypeHint": record_type_hint}}
        ],
    )


def unreadable_search_error(
    *,
    search_name: str,
    record_type: str,
    detail: str,
    available_searches: list[str],
    record_type_hint: str | None,
) -> ValidationError:
    """WDK refused the search definition, so the record type's catalog is offered."""
    context = _UnreadableSearchContext(
        record_type=record_type,
        available_searches=available_searches,
        record_type_hint=record_type_hint,
    )
    return ValidationError(
        title=f"Unknown or invalid search: {search_name}",
        detail=detail,
        errors=[{"context": context.model_dump(by_alias=True, mode="json")}],
    )


def wdk_rejection_error(validation: StepValidation) -> ValidationError:
    """WDK judged the caller's values while answering and refused them."""
    return ValidationError(
        title="Invalid parameter value",
        detail=(
            "; ".join(validation.messages()) or "WDK rejected these parameter values."
        ),
        errors=bundle_rows(validation),
    )


async def collect_available_search_names(
    discovery: DiscoveryService, site_id: str, resolved_record_type: str
) -> list[str]:
    """The search names a record type publishes."""
    searches = await discovery.get_searches(site_id, resolved_record_type)
    return [s.url_segment for s in searches]


async def find_search_record_type_hint(
    discovery: DiscoveryService, ctx: SearchContext
) -> str | None:
    """Search other record types to find where *search_name* actually lives."""
    try:
        record_types = await discovery.get_record_types(ctx.site_id)
        for rt in record_types:
            rt_name = rt.url_segment
            if not rt_name or rt_name == ctx.record_type:
                continue
            rt_searches = await discovery.get_searches(ctx.site_id, rt_name)
            for s in rt_searches:
                if ctx.search_name == s.url_segment:
                    return rt_name
    except VEuPathDBError as hint_exc:
        logger.warning(
            "Record type hint resolution failed",
            search_name=ctx.search_name,
            error=str(hint_exc),
        )
    return None
