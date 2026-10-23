"""The user-independent WDK catalog reads the MCP server publishes."""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from veupathdb import JSONObject
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import PHYLETIC_LIST_PARAMS, ParamValue
from veupathdb.errors import VEuPathDBError

from veupathdb_mcp.catalog import (
    experiments,
    parameters,
    search_inspection,
    searches,
    sites,
)
from veupathdb_mcp.catalog.discovery_service import get_discovery_service
from veupathdb_mcp.catalog.experiment_card import ExperimentCard
from veupathdb_mcp.catalog.experiments import ExperimentMatch, UnknownExperimentError
from veupathdb_mcp.catalog.hidden_params import HiddenParameterError
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
from veupathdb_mcp.catalog.phyletic_builder import (
    PhyleticExpressionResult,
    write_phyletic_expression,
)
from veupathdb_mcp.catalog.phyletic_pattern import PhyleticPattern
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


async def build_phyletic_expression(
    site_id: str, pattern: PhyleticPattern
) -> PhyleticExpressionResult:
    """Write OrthoMCL's phyletic_expression from a pattern, check it against the
    site's taxonomy, and count the groups it returns with one count read.

    Describe the groups you want; the tool writes the expression. Codes are clade
    or genome codes from lookup_phyletic_codes. A genome with no protein in a group
    counts 0, so at_most and fewer_than include groups absent from the set.

    A pattern is one of these, nested freely:
    - count: {"kind": "count", "of": SET, "measure": M, "condition": C,
      "value": V}. M is genomes (genomes of the set holding a protein), proteins
      (the group's proteins over the set) or share (percent of the set's genomes
      holding a protein). C is at_least, at_most, exactly, more_than or
      fewer_than. {"kind": "count", "of": SET, "condition": "absent"} is no
      protein in any genome of the set, with no measure and no value.
    - compare: {"kind": "compare", "left": SET, "right": SET, "reading": R,
      "condition": C, "factor": F} holds when left C F times right, F defaulting
      to 1. R states what is compared: per_genome compares each genome of left
      with each genome of right; totals compares the protein totals of the two
      sets; averages compares proteins per genome, each total divided by its set's
      genome count. The tool reads the largest count it needs from the site and
      writes one band per count.
    - all_of, any_of, none_of: {"kind": "all_of", "terms": [PATTERN, ...]} holds
      when every term holds, any_of when one does, none_of when none does.

    A SET is one of:
    - {"kind": "codes", "codes": ["X"]}: clade X; ["A", "B"] is genomes A and B
      read together; ["ALL"] is every genome.
    - {"kind": "all_except", "codes": ["X"]}: every genome outside clade X.
    - {"kind": "each_species_of", "codes": ["X"]}: the count holds within every
      species of clade X, each on its own. A species is the genomes whose labels
      share the genus and species words.
    - {"kind": "each_genome_of", "codes": ["X"]}: the count holds in every genome
      of clade X, each on its own.
    compare takes codes and all_except only.

    Rounding: a share p of a set of N genomes is exact. at_least p is at least
    ceil(p*N/100) genomes, more_than is more than floor(p*N/100), at_most is at
    most floor(p*N/100), fewer_than is fewer than ceil(p*N/100), and exactly holds
    only when p*N/100 is a whole number. Within each_species_of, N is each
    species' genome count. A compare factor rounds its bound the same way.

    The result gives expression (the value for phyletic_expression; it can run to
    hundreds of thousands of characters, so a host that sets the search for you
    should keep it and bind it by reference rather than ask you to repeat it),
    reading (the expression in words, or for a long expression the pattern's
    sets and conditions with its OR terms and characters), groups (the groups it
    returns), codes (the codes it names) and maximumReads (count reads made for
    the largest counts a compare needs). A refusal from the site is returned as
    the site wrote it. A pattern whose expression would be longer than the
    longest expression the site was measured to answer, or whose count would
    pass the call budget, is refused before the count with its OR terms and
    characters; narrow the pattern and call again.

    Args:
        site_id: The OrthoMCL site, 'orthomcl'.
        pattern: The groups to select, as described above.
    """
    try:
        return await write_phyletic_expression(site_id, pattern)
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
    try:
        return await search_inspection.read_parameter_options(
            site_id,
            search_name,
            parameter_id,
            record_type=record_type,
            context_values=context_values,
            narrowing=search_inspection.VocabNarrowing(query=query),
        )
    except HiddenParameterError as exc:
        raise ToolError(exc.detail or exc.title) from exc


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
    specs = build_param_specs(inspection.definition)
    shown = {spec.name for spec in specs if spec.is_visible}
    return [
        spec.model_copy(
            update={
                "dependent_params": [
                    name for name in spec.dependent_params if name in shown
                ]
            }
        )
        for spec in specs
        if spec.name in shown
    ]


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
            A hidden parameter takes no stated value. On a phylogenetic profile
            search, state included_species and excluded_species; profile_pattern
            is derived from them.
    """
    try:
        definition = (
            (
                await get_discovery_service().get_search_details(
                    SearchContext(site_id, record_type, search_name),
                    expand_params=True,
                )
            ).search_data.parameters
            or []
            if PHYLETIC_LIST_PARAMS & (overrides or {}).keys()
            else []
        )
        resolved = await resolve_params_with_intent(
            fetch_at=wdk_fetch_at(site_id, record_type, search_name),
            intent=ParamIntent(text=criterion),
            overrides=overrides,
            definition=definition,
        )
    except VEuPathDBError as exc:
        raise ToolError(exc.detail or exc.title) from exc
    shown = [shortlist_slot(slot, criterion) for slot in resolved.open_slots]
    return resolved.model_copy(update={"open_slots": shown})
