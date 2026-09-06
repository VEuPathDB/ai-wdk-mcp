"""The user-independent WDK catalog reads the MCP server publishes."""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from veupathdb.json_types import JSONObject

from veupathdb_mcp.catalog import parameters, search_inspection, searches, sites
from veupathdb_mcp.catalog.models import RecordTypeInfo, SearchMatch
from veupathdb_mcp.catalog.overview_formatting import SearchOverviewResult
from veupathdb_mcp.catalog.param_formatting import GetParameterOptionsResult
from veupathdb_mcp.catalog.search_inspection import UnknownSearchError
from veupathdb_mcp.catalog.searches import VagueSearchQueryError
from veupathdb_mcp.tool_errors import ToolErrorPayload
from veupathdb_mcp.tool_payloads import (
    SearchCategory,
    SearchListing,
    TransformListing,
    list_search_categories,
    list_search_listings,
    list_transform_listings,
    rank_example_plans,
)


def _payload_or_error(result: JSONObject | ToolErrorPayload) -> JSONObject:
    """Turn a service's error payload into a tool error that names its cause."""
    match result:
        case ToolErrorPayload():
            raise ToolError(result.message)
        case _:
            return result


async def list_record_types(site_id: str) -> list[RecordTypeInfo]:
    """List the record types a VEuPathDB site publishes.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
    """
    return await sites.get_record_types(site_id)


async def search_for_searches(
    site_id: str,
    query: str,
    record_type: str = "transcript",
    keywords: list[str] | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[SearchMatch]:
    """Rank a site's searches against a description of what to find.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        query: What you are looking for, in as much detail as you have.
        record_type: Record type to rank within. Gene searches are 'transcript'.
        keywords: Exact identifiers to match against search names.
        category: One category of the site ontology to restrict the candidates.
        limit: Largest number of matches to return.
    """
    try:
        return await searches.search_for_searches(
            site_id,
            record_type=record_type,
            query=query,
            keywords=keywords or [],
            category=category,
            limit=limit,
        )
    except VagueSearchQueryError as exc:
        msg = f"query is not usable. {exc.rejection.message}"
        raise ToolError(msg) from exc


async def browse_search_categories(
    site_id: str,
    record_type: str = "transcript",
) -> list[SearchCategory]:
    """List the site ontology's search categories with example search names.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        record_type: Record type. Gene searches are 'transcript'.
    """
    return await list_search_categories(site_id, record_type)


async def list_searches(
    site_id: str,
    record_type: str = "transcript",
) -> list[SearchListing]:
    """List every search name of one record type, without descriptions.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        record_type: Record type. Gene searches are 'transcript'.
    """
    return await list_search_listings(site_id, record_type)


async def list_transforms(
    site_id: str,
    record_type: str = "transcript",
) -> list[TransformListing]:
    """List the searches that accept an input step, with their descriptions.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        record_type: Record type. Gene searches are 'transcript'.
    """
    return await list_transform_listings(site_id, record_type)


async def lookup_phyletic_codes(
    site_id: str,
    query: str,
    record_type: str = "transcript",
) -> JSONObject:
    """Look up the species and clade codes GenesByOrthologPattern accepts.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        query: Species or clade name, for example 'falciparum' or 'Apicomplexa'.
        record_type: Record type. Gene searches are 'transcript'.
    """
    return _payload_or_error(
        await parameters.lookup_phyletic_codes(site_id, record_type, query)
    )


async def search_example_plans(
    site_id: str,
    query: str,
    limit: int = 3,
) -> list[JSONObject]:
    """Rank the site's public strategies against a research goal.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        query: The research goal to match public strategies against.
        limit: Largest number of strategies to return.
    """
    return await rank_example_plans(site_id, query, limit)


async def get_search_overview(
    site_id: str,
    search_name: str,
    record_type: str | None = None,
    query: str | None = None,
) -> SearchOverviewResult:
    """Read one search: what it returns, and the parameters it takes.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        search_name: WDK search urlSegment, for example 'GenesByMolecularWeight'.
        record_type: Record type. Omit to resolve it from the site catalog.
        query: Terms that rank an oversized parameter vocabulary.
    """
    try:
        inspection = await search_inspection.inspect_search(
            site_id, search_name, record_type=record_type, query=query
        )
    except UnknownSearchError as exc:
        msg = f"search_name is not on this site. {exc.guidance}"
        raise ToolError(msg) from exc
    return inspection.overview


async def get_parameter_options(
    site_id: str,
    search_name: str,
    parameter_id: str,
    record_type: str | None = None,
    context_values: dict[str, str] | None = None,
    query: str | None = None,
) -> GetParameterOptionsResult:
    """Read one parameter's vocabulary under the parent values supplied.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        search_name: WDK search urlSegment the parameter belongs to.
        parameter_id: Parameter name to read.
        record_type: Record type. Omit to resolve it from the site catalog.
        context_values: Values of the parameters this one depends on.
        query: Terms that narrow a vocabulary too large to travel whole.
    """
    return await search_inspection.read_parameter_options(
        site_id,
        search_name,
        parameter_id,
        record_type=record_type,
        context_values=context_values,
        narrowing=search_inspection.VocabNarrowing(query=query),
    )
