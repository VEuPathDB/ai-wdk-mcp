"""The MCP tools that act as the VEuPathDB user whose bearer the call carries."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field
from veupathdb.domain.parameters import ParamValue
from veupathdb.domain.strategy import StrategyAst
from veupathdb.errors import ValidationError, VEuPathDBError
from veupathdb.wdk import WDKAnswer, get_strategy_api

from veupathdb_mcp.audit import RECORD_READS_PER_CALL
from veupathdb_mcp.catalog import NoGeneRecordsError
from veupathdb_mcp.controls.control_tests import (
    run_positive_negative_controls,
    run_step_control_tests,
)
from veupathdb_mcp.controls.control_types import (
    ControlTestResult,
    IntersectionConfig,
)
from veupathdb_mcp.gene_lookup import (
    MAX_GENE_IDS,
    GeneResolveResult,
    GeneSearchResult,
    lookup_genes_by_text,
    normalize_gene_ids,
    read_gene_ids,
)
from veupathdb_mcp.tool_payloads import StepDownloadUrl, gene_sample_attributes
from veupathdb_mcp.wdk.ai_expression import (
    GeneExpressionSummary,
    get_gene_expression_summary,
)
from veupathdb_mcp.wdk.column_counts import (
    DEFAULT_COLUMN_COUNT_TOP,
    MAX_COLUMN_COUNT_TOP,
    ColumnCounts,
    ColumnNotCountedError,
    StepColumns,
    count_by_column,
    list_step_columns,
)
from veupathdb_mcp.wdk.enrichment.gene_ids import (
    GeneIdEnrichment,
    enrich_gene_ids_by_value,
)
from veupathdb_mcp.wdk.enrichment.types import (
    BackgroundSource,
    EnrichmentAnalysisType,
)
from veupathdb_mcp.wdk.gene_set_steps import (
    DEFAULT_GENE_SET_STRATEGY_NAME,
    StepTooLargeError,
    fetch_gene_ids_from_step,
    frozen_step_id,
)
from veupathdb_mcp.wdk.plan_counts import (
    DEFAULT_PLAN_COUNTS_STRATEGY_NAME,
    compute_plan_step_counts,
)
from veupathdb_mcp.wdk.step_preview import step_download_url, step_sample_answer
from veupathdb_mcp.wdk.step_size import (
    StepCountResult,
    get_estimated_size_for_site,
)

# A call past a bound is refused by name, not narrowed in silence.
type GeneRecordLimit = Annotated[int, Field(ge=1, le=50)]
type SampleRecordLimit = Annotated[int, Field(ge=1, le=100)]
type RecordReadIds = Annotated[list[str], Field(max_length=RECORD_READS_PER_CALL)]
type ColumnCountTop = Annotated[int, Field(ge=1, le=MAX_COLUMN_COUNT_TOP)]


_NO_CONTROL_GENE = "positive_controls or negative_controls must name a gene id."


def _bounded_gene_ids(gene_ids: list[str]) -> list[str]:
    """Refuse an empty or oversized gene list by name."""
    ids = normalize_gene_ids(gene_ids)
    if not ids:
        msg = "gene_ids holds no gene identifier."
        raise ToolError(msg)
    if len(ids) > RECORD_READS_PER_CALL:
        msg = (
            f"gene_ids holds {len(ids)} identifiers; one call takes at most "
            f"{RECORD_READS_PER_CALL}."
        )
        raise ToolError(msg)
    return ids


async def lookup_gene_records(
    site_id: str,
    query: str,
    organism: str | None = None,
    limit: GeneRecordLimit = 10,
) -> GeneSearchResult:
    """Find gene records by name, symbol, product description or keyword.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        query: Free text, for example 'PfAP2-G' or 'gametocyte surface antigen'.
        organism: Organism to restrict to, for example 'Plasmodium falciparum 3D7'.
        limit: Largest number of records to return.
    """
    return await lookup_genes_by_text(site_id, query, organism=organism, limit=limit)


async def resolve_gene_ids_to_records(
    site_id: str,
    gene_ids: RecordReadIds,
) -> GeneResolveResult:
    """Resolve gene identifiers to records, each read from its own gene record.

    One call takes at most 80 identifiers. A previous or alternate id resolves
    to the gene it names now. An id no gene record names is matched against gene
    and transcript ids by the site's text search. When one id names several
    genes, holds a wildcard or a space, or matches more than 50 transcripts, the
    call answers an error and no records. A site that lists no gene record type,
    such as OrthoMCL, is refused by name. The call writes nothing into the
    account.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene_ids: Gene or locus tag identifiers, for example ['PF3D7_1222600'].
    """
    try:
        return await read_gene_ids(site_id, _bounded_gene_ids(gene_ids))
    except NoGeneRecordsError as exc:
        raise ToolError(exc.detail or exc.title) from exc


async def get_ai_expression_summary(
    site_id: str,
    gene_id: str,
) -> GeneExpressionSummary:
    """Read the site's own AI summary of one gene's expression data.

    The site generates and caches these summaries itself. A gene the site has
    not summarized answers with `unavailableReason` and no summary.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene_id: A gene source id on that site, for example 'PF3D7_1133400'.
    """
    try:
        return await get_gene_expression_summary(site_id, gene_id)
    except VEuPathDBError as exc:
        raise ToolError(exc.detail) from exc


# ---------------------------------------------------------------------------
# Step reads: they name a user's own step, so they need that user's bearer.
# ---------------------------------------------------------------------------


async def get_step_estimated_size(
    site_id: str,
    wdk_step_id: int,
    wdk_strategy_id: int | None = None,
) -> StepCountResult:
    """Count the results of a step that is already built in WDK.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        wdk_step_id: WDK step id.
        wdk_strategy_id: WDK strategy id, which an imported strategy requires.
    """
    return await get_estimated_size_for_site(site_id, wdk_step_id, wdk_strategy_id)


async def get_step_sample_records(
    site_id: str,
    wdk_step_id: int,
    record_type: str,
    limit: SampleRecordLimit = 5,
) -> WDKAnswer:
    """Read the first records of a step that is already built in WDK.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        wdk_step_id: WDK step id.
        record_type: Record type of the step. Gene steps are 'transcript'.
        limit: Number of records to return.
    """
    return await step_sample_answer(
        site_id,
        wdk_step_id,
        limit=limit,
        attributes=gene_sample_attributes(record_type),
    )


async def get_step_download_url(
    site_id: str,
    wdk_step_id: int,
    output_format: Literal["csv", "tab", "json"] = "csv",
    attributes: list[str] | None = None,
) -> StepDownloadUrl:
    """Create a temporary download URL for a step's results.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        wdk_step_id: WDK step id.
        output_format: Download format.
        attributes: Attributes to include. Omit for the WDK default set.
    """
    url = await step_download_url(
        site_id,
        wdk_step_id,
        output_format=output_format,
        attributes=attributes,
    )
    return StepDownloadUrl(step_id=wdk_step_id, format=output_format, download_url=url)


# ---------------------------------------------------------------------------
# Evidence: the two tools that write into the calling user's account.
# ---------------------------------------------------------------------------


async def run_control_tests_on_search(
    site_id: str,
    target_search_name: str,
    target_parameters: dict[str, ParamValue],
    positive_controls: list[str] | None = None,
    negative_controls: list[str] | None = None,
    record_type: str = "transcript",
) -> ControlTestResult:
    """Intersect a search's results with known control genes.

    Creates a temporary WDK strategy in the calling user's account. Each call
    writes one dataset into the calling user's WDK account, which WDK cannot
    delete.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        target_search_name: WDK search urlSegment to test.
        target_parameters: Parameter values, each in its typed shape.
        positive_controls: Gene ids the search should return.
        negative_controls: Gene ids the search should not return.
        record_type: Record type. Gene searches are 'transcript'.
    """
    positives = normalize_gene_ids(positive_controls or [])
    negatives = normalize_gene_ids(negative_controls or [])
    if not positives and not negatives:
        raise ToolError(_NO_CONTROL_GENE)
    config = IntersectionConfig(
        site_id=site_id,
        record_type=record_type,
        target_search_name=target_search_name,
        target_parameters=dict(target_parameters),
        controls_search_name="GeneByLocusTag",
        controls_param_name="ds_gene_ids",
        controls_value_format="newline",
    )
    return await run_positive_negative_controls(
        config,
        positive_controls=positives,
        negative_controls=negatives,
    )


async def enrich_gene_ids(
    site_id: str,
    gene_ids: list[str],
    background: BackgroundSource | None = None,
    enrichment_types: list[EnrichmentAnalysisType] | None = None,
) -> GeneIdEnrichment:
    """Run over-representation analysis on a gene list given by value.

    Creates a temporary WDK step in the calling user's account. Each call
    writes one dataset into the calling user's WDK account, which WDK cannot
    delete.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene_ids: The genes to test, for example ['PF3D7_1222600'].
        background: The annotated genome the test runs against.
        enrichment_types: Analyses to run. Omit to run all five.
    """
    try:
        return await enrich_gene_ids_by_value(
            site_id,
            gene_ids,
            background or BackgroundSource(),
            enrichment_types,
        )
    except ValidationError as exc:
        raise ToolError(str(exc)) from exc


async def get_step_gene_ids(site_id: str, wdk_step_id: int) -> list[str]:
    """Read the gene identifiers a step that is already built in WDK holds.

    A step that holds more genes than one call carries is refused by name.
    Read that one with get_step_download_url.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        wdk_step_id: WDK step id.
    """
    try:
        return await fetch_gene_ids_from_step(
            get_strategy_api(site_id), step_id=wdk_step_id, limit=MAX_GENE_IDS
        )
    except StepTooLargeError as exc:
        msg = (
            f"step {exc.step_id} holds more than {exc.limit} records; one call "
            "answers at most that many. Read the whole step with "
            "get_step_download_url."
        )
        raise ToolError(msg) from exc


async def get_step_columns(site_id: str, wdk_step_id: int) -> StepColumns:
    """List the columns of a step that is already built in WDK.

    The columns are the attributes of the step's record type and the columns
    its own search adds. Each column gives its name, its display name, its data
    type (STRING, NUMBER, DATE or OTHER) and whether count_step_by_column can
    count it. The call writes nothing into the account.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        wdk_step_id: WDK step id.
    """
    return await list_step_columns(site_id, wdk_step_id)


async def count_step_by_column(
    site_id: str,
    wdk_step_id: int,
    column: str,
    top: ColumnCountTop = DEFAULT_COLUMN_COUNT_TOP,
) -> ColumnCounts:
    """Count the records of a built WDK step by the values of one column.

    The step can be any step: a search, a combined step or a transform step
    such as an ortholog transform. The site counts the step's whole result, so
    this answers which values occur most, for example which organisms hold the
    most records or which products are the most common. A string column answers
    its values ranked by record count, largest first, at most top of them, and
    distinctValues says how many values exist in all. A number column answers
    the site's histogram bins and the column's minimum, maximum and mean. On a
    transcript step a gene counts once for each of its transcripts.

    Choose the column with get_step_columns first: only a column it marks
    countable is counted, and any other column is refused with the names of the
    columns that can be counted. The call writes nothing into the account.

    Args:
        site_id: VEuPathDB site, for example 'orthomcl'.
        wdk_step_id: WDK step id.
        column: Column name from get_step_columns, for example 'organism'.
        top: Largest number of string values to return.
    """
    try:
        return await count_by_column(site_id, wdk_step_id, column, top)
    except ColumnNotCountedError as exc:
        msg = f"{exc.detail}. get_step_columns lists every column of the step."
        raise ToolError(msg) from exc


async def run_control_tests_on_step(
    site_id: str,
    wdk_step_id: int,
    positive_controls: list[str] | None = None,
    negative_controls: list[str] | None = None,
) -> ControlTestResult:
    """Intersect a step that is already built in WDK with known control genes.

    Creates a copy of the step, a controls step and a temporary WDK strategy in
    the calling user's account, and deletes them when the test ends. Each call
    writes one dataset into the calling user's WDK account, which WDK cannot
    delete.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        wdk_step_id: WDK step id.
        positive_controls: Gene ids the step should hold.
        negative_controls: Gene ids the step should not hold.
    """
    positives = normalize_gene_ids(positive_controls or [])
    negatives = normalize_gene_ids(negative_controls or [])
    if not positives and not negatives:
        raise ToolError(_NO_CONTROL_GENE)
    return await run_step_control_tests(
        site_id,
        wdk_step_id,
        positive_controls=positives,
        negative_controls=negatives,
    )


async def count_plan_steps(
    site_id: str,
    plan: StrategyAst,
    strategy_name: str = DEFAULT_PLAN_COUNTS_STRATEGY_NAME,
) -> dict[str, int | None]:
    """Count every step of a plan WDK has not built yet, keyed by plan step id.

    A plan of searches alone is counted without a strategy. Any other plan
    needs a temporary internal strategy in the calling user's account, which
    is deleted once its counts are read. A step whose count cannot be read is
    reported as null.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        plan: The strategy plan to count, in its own step ids.
        strategy_name: Name of the temporary strategy a combined plan needs.
    """
    return await compute_plan_step_counts(plan, site_id, strategy_name=strategy_name)


async def create_gene_set_step(
    site_id: str,
    gene_ids: list[str],
    strategy_name: str = DEFAULT_GENE_SET_STRATEGY_NAME,
) -> int | None:
    """Materialize gene identifiers as a WDK step that holds exactly them.

    Creates a WDK step and an internal strategy in the calling user's account.
    Each call that creates a step writes one dataset into the calling user's WDK
    account, which WDK cannot delete. A list this server already made a step of
    for the user reuses that step. An empty list creates nothing and answers null.
    A site that lists no gene-list search refuses the call before it writes.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene_ids: The genes the step holds, for example ['PF3D7_1222600'].
        strategy_name: Name of the internal strategy that holds the step.
    """
    return await frozen_step_id(
        site_id,
        normalize_gene_ids(gene_ids),
        strategy_name=strategy_name,
    )
