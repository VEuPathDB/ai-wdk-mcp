"""The user-independent WDK catalog reads the MCP server publishes."""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from veupathdb import JSONObject
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import ParamValue
from veupathdb.errors import VEuPathDBError

from veupathdb_mcp.catalog import parameters, search_inspection, searches, sites
from veupathdb_mcp.catalog.models import ParamSpecResponse, RecordTypeInfo, SearchMatch
from veupathdb_mcp.catalog.overview_formatting import SearchOverviewResult
from veupathdb_mcp.catalog.param_dag import (
    ResolvedParams,
    resolve_params_with_intent,
    wdk_fetch_at,
)
from veupathdb_mcp.catalog.param_formatting import GetParameterOptionsResult
from veupathdb_mcp.catalog.param_intent import ParamIntent
from veupathdb_mcp.catalog.param_specs_formatting import build_param_specs
from veupathdb_mcp.catalog.param_validation import ValidatedParams, validate_parameters
from veupathdb_mcp.catalog.search_inspection import UnknownSearchError
from veupathdb_mcp.catalog.searches import VagueSearchQueryError
from veupathdb_mcp.catalog.validation_callbacks import make_validation_callbacks
from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError
from veupathdb_mcp.embeddings.record_manager import IndexHit, search_index
from veupathdb_mcp.embeddings.semantic_index import catalog_index_id
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


async def get_search_param_specs(
    site_id: str,
    search_name: str,
    record_type: str | None = None,
) -> list[ParamSpecResponse]:
    """Read one search's parameters in their normalized spec shape.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        search_name: WDK search urlSegment, for example 'GenesByMolecularWeight'.
        record_type: Record type. Omit to resolve it from the site catalog.
    """
    try:
        inspection = await search_inspection.inspect_search(
            site_id, search_name, record_type=record_type
        )
    except UnknownSearchError as exc:
        msg = f"search_name is not on this site. {exc.guidance}"
        raise ToolError(msg) from exc
    return build_param_specs(inspection.definition)


async def validate_search_parameters(
    site_id: str,
    search_name: str,
    parameter_values: dict[str, ParamValue],
    record_type: str | None = None,
) -> ValidatedParams:
    """Canonicalize a search's parameter values, and have WDK judge them.

    The result carries the values WDK accepts, the record class the search
    runs under, and the names nobody chose.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        search_name: WDK search urlSegment the values belong to.
        parameter_values: Parameter values, each in its typed shape.
        record_type: Record type. Omit to resolve it from the site catalog.
    """
    try:
        return await validate_parameters(
            SearchContext(site_id, record_type or "", search_name),
            parameters=parameter_values,
            callbacks=make_validation_callbacks(site_id),
        )
    except VEuPathDBError as exc:
        raise ToolError(exc.detail or exc.title) from exc


async def search_catalog_index(
    site_id: str,
    query: str,
    top_k: int = 20,
) -> list[IndexHit]:
    """Rank one site's indexed searches by similarity to a description.

    An entry id is the record type and the search name, separated by a slash.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        query: What you are looking for, in as much detail as you have.
        top_k: Largest number of entries to return.
    """
    try:
        return await search_index(catalog_index_id(site_id), query, top_k)
    except SemanticIndexUnavailableError as exc:
        msg = f"The semantic index is unavailable. {exc}"
        raise ToolError(msg) from exc


async def resolve_search_parameters(
    site_id: str,
    search_name: str,
    record_type: str = "transcript",
    criterion: str = "",
    overrides: dict[str, str | list[str]] | None = None,
) -> ResolvedParams:
    """Bind a search's parameters, and name the ones nothing bound.

    Each parameter takes the value the overrides state, the only value its
    vocabulary allows, or its own default. What none of those reach is an open
    slot the caller answers.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        search_name: WDK search urlSegment to bind.
        record_type: Record type. Gene searches are 'transcript'.
        criterion: The criterion the binding runs against, in your own words.
        overrides: Values stated by name, each a string or a list of strings.
    """
    try:
        return await resolve_params_with_intent(
            fetch_at=wdk_fetch_at(site_id, record_type, search_name),
            intent=ParamIntent(text=criterion),
            overrides=overrides,
        )
    except VEuPathDBError as exc:
        raise ToolError(exc.detail or exc.title) from exc
