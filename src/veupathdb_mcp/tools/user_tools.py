"""The MCP tools that act as the VEuPathDB user whose bearer the call carries."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp.exceptions import ToolError
from pydantic import Field
from veupathdb.domain.parameters.values import ParamValue
from veupathdb.errors import ValidationError, VEuPathDBError
from veupathdb.wdk.wdk_models import WDKAnswer

from veupathdb_mcp.controls.control_tests import run_positive_negative_controls
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
    resolve_gene_ids,
)
from veupathdb_mcp.tool_payloads import StepDownloadUrl, gene_sample_attributes
from veupathdb_mcp.wdk.ai_expression import (
    GeneExpressionSummary,
    get_gene_expression_summary,
)
from veupathdb_mcp.wdk.enrichment.gene_ids import (
    GeneIdEnrichment,
    enrich_gene_ids_by_value,
)
from veupathdb_mcp.wdk.enrichment.types import (
    BackgroundSource,
    EnrichmentAnalysisType,
)
from veupathdb_mcp.wdk.step_preview import step_download_url
from veupathdb_mcp.wdk.step_results import step_results_service
from veupathdb_mcp.wdk.step_size import (
    StepCountResult,
    get_estimated_size_for_site,
)

# A call past a bound is refused by name, not narrowed in silence.
type GeneRecordLimit = Annotated[int, Field(ge=1, le=50)]
type SampleRecordLimit = Annotated[int, Field(ge=1, le=100)]


def _bounded_gene_ids(gene_ids: list[str]) -> list[str]:
    """Refuse an empty or oversized gene list by name."""
    ids = normalize_gene_ids(gene_ids)
    if not ids:
        msg = "gene_ids holds no gene identifier."
        raise ToolError(msg)
    if len(ids) > MAX_GENE_IDS:
        msg = (
            f"gene_ids holds {len(ids)} identifiers; one call takes at most "
            f"{MAX_GENE_IDS}."
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
    gene_ids: list[str],
    record_type: str = "transcript",
    search_name: str = "GeneByLocusTag",
    param_name: str = "ds_gene_ids",
) -> GeneResolveResult:
    """Resolve gene identifiers to full records.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene_ids: Gene or locus tag identifiers, for example ['PF3D7_1222600'].
        record_type: Record type. Gene searches are 'transcript'.
        search_name: WDK search that accepts an identifier list.
        param_name: Parameter of that search which carries the identifier list.
    """
    return await resolve_gene_ids(
        site_id,
        _bounded_gene_ids(gene_ids),
        record_type=record_type,
        search_name=search_name,
        param_name=param_name,
    )


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
    results = step_results_service(
        site_id=site_id,
        step_id=wdk_step_id,
        record_type=record_type,
    )
    return await results.get_records(
        limit=limit, attributes=gene_sample_attributes(record_type)
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

    Creates a temporary WDK strategy in the calling user's account.

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
        msg = "positive_controls or negative_controls must name a gene id."
        raise ToolError(msg)
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

    Creates a temporary WDK dataset and step in the calling user's account.

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
