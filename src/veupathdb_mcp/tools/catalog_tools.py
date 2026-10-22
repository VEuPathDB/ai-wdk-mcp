"""The user-independent WDK catalog reads the MCP server publishes."""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from veupathdb import JSONObject
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import ParamValue
from veupathdb.errors import VEuPathDBError

from veupathdb_mcp.catalog import (
    clade_only,
    experiments,
    parameters,
    protein_comparison,
    search_inspection,
    searches,
    sites,
)
from veupathdb_mcp.catalog.clade_only import CladeOnlyExpression, EverySpeciesExpression
from veupathdb_mcp.catalog.experiment_card import ExperimentCard
from veupathdb_mcp.catalog.experiments import ExperimentMatch, UnknownExperimentError
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
from veupathdb_mcp.catalog.protein_comparison import ProteinCountComparison
from veupathdb_mcp.catalog.search_inspection import UnknownSearchError
from veupathdb_mcp.catalog.searches import VagueSearchQueryError
from veupathdb_mcp.catalog.shortlist import shortlist_slot
from veupathdb_mcp.catalog.validation_callbacks import make_validation_callbacks
from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError
from veupathdb_mcp.embeddings.record_manager import IndexHit, search_index
from veupathdb_mcp.embeddings.semantic_index import catalog_index_id
from veupathdb_mcp.tool_payloads import (
    SearchCategory,
    SearchListing,
    TransformListing,
    list_search_categories,
    list_search_listings,
    list_transform_listings,
    rank_example_plans,
)
from veupathdb_mcp.tools.refusals import payload_or_error


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

    A query nothing matches returns an empty list. `relevance` is the score
    divided by the best hit's score, so the top hit reads 1.0 however weak it
    is. `semantic_similarity` is the cosine of the query against the search's
    indexed text, or null when the index did not score that search.

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
    """Look up species and clade codes: the ones GenesByOrthologPattern's species
    lists accept, or on OrthoMCL the ones a phyletic_expression names.

    Each match gives its code, its label, leaf (true for one genome) and
    genomes, the number of genomes under it. species groups the genomes the query
    names by species, so the strains of one species are listed together.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb' or 'orthomcl'.
        query: Species or clade name, for example 'falciparum' or 'Apicomplexa'.
        record_type: Record type. Gene searches are 'transcript'.
    """
    return payload_or_error(
        await parameters.lookup_phyletic_codes(site_id, record_type, query)
    )


async def build_protein_count_comparison(
    site_id: str,
    genome_a: str,
    genome_b: str,
    reverse: bool = False,
) -> ProteinCountComparison:
    """Build the exact phyletic_expression for the OrthoMCL groups in which genome
    A holds more proteins than genome B.

    The expression is B=0 AND A>=1 OR B=1 AND A>=2 OR ... OR B=K AND A>=K+1,
    where K is the smallest count for which B>=K+1 returns no group. K is read
    from the site by bisection over count reports, each a count with no records:
    at most 15 count reports, one at a time. A genome B with 1024 or more
    proteins in one group is refused, because its ladder would not finish. Each ladder gives its expression,
    groups, the number of groups it returns, and length, its characters; the
    parameter has no length limit, so pass the expression whole. A group with as
    many proteins in both genomes is in neither ladder.

    Args:
        site_id: The OrthoMCL site, 'orthomcl'.
        genome_a: Genome A, one genome code (leaf=true in lookup_phyletic_codes).
        genome_b: Genome B, one genome code (leaf=true in lookup_phyletic_codes).
        reverse: Also build the ladder of the groups in which genome B holds
            more proteins than genome A.
    """
    try:
        return await protein_comparison.compare_protein_counts(
            site_id, genome_a, genome_b, reverse=reverse
        )
    except VEuPathDBError as exc:
        raise ToolError(exc.detail or exc.title) from exc


async def build_clade_only_expression(
    site_id: str,
    clade: list[str],
    within: list[str] | None = None,
) -> CladeOnlyExpression:
    """Build the exact phyletic_expression for the OrthoMCL groups present in a
    clade L and in no genome outside it.

    The expression is L>=1T AND C=0T, with C every genome outside L, written from
    the site's taxonomy: a clade code for each whole clade outside L and a genome
    code for the rest. With within, a clade M that holds every genome of L, C is
    every genome outside M, so the groups may also hold proteins elsewhere in M.
    One count report counts the groups. The result gives expression, groups,
    length, its characters, genomes, the genome codes of L, and outside, the
    number of genomes C covers; the parameter has no length limit, so pass the
    expression whole. For a clade X whose genomes must hold no protein, write
    L>=1T AND X=0T instead.

    Args:
        site_id: The OrthoMCL site, 'orthomcl'.
        clade: L, one clade code, or the genome codes of a group with no clade
            code of its own, such as a genus, from lookup_phyletic_codes.
        within: M, the codes of a clade that holds every genome of L; every
            genome outside M must hold no protein.
    """
    try:
        return await clade_only.clade_only_expression(site_id, clade, within)
    except VEuPathDBError as exc:
        raise ToolError(exc.detail or exc.title) from exc


async def build_every_species_expression(
    site_id: str, clade: list[str]
) -> EverySpeciesExpression:
    """Build the exact phyletic_expression for the OrthoMCL groups present in every
    species of a clade L.

    The rule: a group is present in a species S of k genomes when at least
    ceil(k/2) of those k genomes hold a protein of the group, the unit
    S>=ceil(k/2)T; a species of one genome is S>=1T. The expression joins one
    unit per species of L with AND, so a group passes only when it is present
    in every species. It is written from the site's taxonomy: the species are
    the genome labels' genus and species words, and each unit names that
    species' genomes. One count report counts the groups. The
    result gives expression, groups, length, its characters, genomes, the genome
    codes of L, and species, each species with its genomes and present, the
    genomes that must hold a protein; the parameter has no length limit, so pass
    the expression whole. For presence in every genome write L=NT instead, and
    for presence in some genome L>=1T. A clade of one species is refused: write
    its one unit by hand.

    Args:
        site_id: The OrthoMCL site, 'orthomcl'.
        clade: L, one clade code, or the genome codes of a group with no clade
            code of its own, such as a genus, from lookup_phyletic_codes.
    """
    try:
        return await clade_only.every_species_expression(site_id, clade)
    except VEuPathDBError as exc:
        raise ToolError(exc.detail or exc.title) from exc


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
    query: str | list[str] | None = None,
) -> GetParameterOptionsResult:
    """Read one parameter's vocabulary under the parent values supplied.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        search_name: WDK search urlSegment the parameter belongs to.
        parameter_id: Parameter name to read.
        record_type: Record type. Omit to resolve it from the site catalog.
        context_values: Values of the parameters this one depends on.
        query: One phrase, or several phrasings of one concept, that narrow the
            vocabulary. Hyphen and space match alike, and a phrase also
            matches its words in any order.
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


async def rank_experiments_elsewhere(
    site_id: str,
    query: str,
    limit: int = 3,
) -> list[ExperimentMatch]:
    """Rank the experiments of the other VEuPathDB sites against a description.

    Each match is a dataset of another site, labelled with that site, and one
    site gives one match at most. None of them can be bound on site_id: read
    one to take its condition, stage or organism into a search on site_id.

    Args:
        site_id: The site the caller works on, for example 'plasmodb'.
        query: What you are looking for, in as much detail as you have.
        limit: Largest number of sites to return a match from.
    """
    try:
        return await experiments.rank_experiments_elsewhere(site_id, query, limit=limit)
    except SemanticIndexUnavailableError as exc:
        msg = f"The experiment index is unavailable. {exc}"
        raise ToolError(msg) from exc


async def read_experiment(site_id: str, dataset_id: str) -> ExperimentCard:
    """Read one dataset of a VEuPathDB site: what it measured, and what it feeds.

    Args:
        site_id: The site that publishes the dataset, for example 'cryptodb'.
        dataset_id: WDK dataset id, for example 'DS_00f985857c'.
    """
    try:
        return await experiments.read_experiment(site_id, dataset_id)
    except UnknownExperimentError as exc:
        msg = f"dataset_id is not a dataset of {site_id}. {exc}"
        raise ToolError(msg) from exc
    except SemanticIndexUnavailableError as exc:
        msg = f"The experiment index is unavailable. {exc}"
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
    slot the caller answers. A long slot vocabulary is cut to the values the
    criterion names best; get_parameter_options with query='<words>' reads the
    values the cut left out.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        search_name: WDK search urlSegment to bind.
        record_type: Record type. Gene searches are 'transcript'.
        criterion: The criterion the binding runs against, in your own words.
        overrides: Values stated by name, each a string or a list of strings.
    """
    try:
        resolved = await resolve_params_with_intent(
            fetch_at=wdk_fetch_at(site_id, record_type, search_name),
            intent=ParamIntent(text=criterion),
            overrides=overrides,
        )
    except VEuPathDBError as exc:
        raise ToolError(exc.detail or exc.title) from exc
    shown = [shortlist_slot(slot, criterion) for slot in resolved.open_slots]
    return resolved.model_copy(update={"open_slots": shown})
