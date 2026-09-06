"""WDK async helpers and context types for gene set operations."""

from dataclasses import dataclass
from typing import Literal

from veupathdb.domain.parameters.values import InputDatasetValue, ParamValue
from veupathdb.errors import VEuPathDBError
from veupathdb.logging import get_logger
from veupathdb.wdk.factory import (
    get_strategy_api,
)
from veupathdb.wdk.strategy_api.api import StrategyAPI
from veupathdb.wdk.wdk_models import (
    WDKDatasetConfigIdList,
    WDKDatasetIdListContent,
)

from veupathdb_mcp.wdk.helpers import extract_record_ids

logger = get_logger(__name__)

SetOperation = Literal["intersect", "union", "minus"]


@dataclass
class GeneSetWdkContext:
    """Optional WDK-related context for gene set creation."""

    wdk_strategy_id: int | None = None
    wdk_step_id: int | None = None
    search_name: str | None = None
    record_type: str | None = None
    parameters: dict[str, ParamValue] | None = None


# ---------------------------------------------------------------------------
# Low-level WDK helpers
# ---------------------------------------------------------------------------


async def build_enrichment_params_from_gene_ids(
    site_id: str,
    gene_ids: list[str],
) -> tuple[str, dict[str, ParamValue], str]:
    """Create a WDK dataset from gene IDs and return enrichment parameters.

    The dataset is temporary and is addressed by a locus-tag search.
    """
    api = get_strategy_api(site_id)
    config = WDKDatasetConfigIdList(
        source_type="idList",
        source_content=WDKDatasetIdListContent(ids=gene_ids),
    )
    dataset_id = await api.create_dataset(config)
    return (
        "GeneByLocusTag",
        {"ds_gene_ids": InputDatasetValue(dataset_id=str(dataset_id))},
        "transcript",
    )


async def resolve_root_step_id(api: StrategyAPI, *, strategy_id: int) -> int | None:
    """Get the root step ID from a WDK strategy."""
    strategy = await api.get_strategy(strategy_id)
    return strategy.root_step_id


async def fetch_gene_ids_from_step(api: StrategyAPI, *, step_id: int) -> list[str]:
    """Fetch all gene IDs from a WDK step via the standard report endpoint."""
    answer = await api.get_step_answer(
        step_id,
        attributes=["primary_key"],
        pagination={"offset": 0, "numRecords": -1},
    )
    return extract_record_ids(answer.records)


# ---------------------------------------------------------------------------
# WDK context resolution
# ---------------------------------------------------------------------------


async def resolve_wdk_context(
    site_id: str,
    gene_ids: list[str],
    ctx: GeneSetWdkContext,
) -> tuple[list[str], GeneSetWdkContext, int]:
    """Resolve gene IDs and search context from a WDK strategy."""
    wdk_strategy_id = ctx.wdk_strategy_id
    if gene_ids or wdk_strategy_id is None:
        return gene_ids, ctx, 1

    api = get_strategy_api(site_id)
    wdk_step_id = ctx.wdk_step_id
    search_name = ctx.search_name
    record_type = ctx.record_type
    parameters = ctx.parameters
    step_count = 1

    wdk_step_id = await _resolve_root_step(api, wdk_strategy_id, wdk_step_id)
    gene_ids = await _fetch_step_genes(api, wdk_step_id)
    step_count = await _count_strategy_steps(api, wdk_strategy_id)

    if wdk_step_id is not None and search_name is None and step_count == 1:
        (
            search_name,
            record_type,
            parameters,
        ) = await _extract_step_search_context(api, wdk_step_id, record_type)

    updated = GeneSetWdkContext(
        wdk_strategy_id=wdk_strategy_id,
        wdk_step_id=wdk_step_id,
        search_name=search_name,
        record_type=record_type,
        parameters=parameters,
    )
    return gene_ids, updated, step_count


async def _resolve_root_step(
    api: StrategyAPI, strategy_id: int, step_id: int | None
) -> int | None:
    if step_id is not None:
        return step_id
    try:
        resolved = await resolve_root_step_id(api, strategy_id=strategy_id)
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to resolve root step from strategy",
            strategy_id=strategy_id,
            error=str(exc),
        )
        return step_id
    else:
        logger.info(
            "Resolved root step from strategy",
            strategy_id=strategy_id,
            step_id=resolved,
        )
        return resolved


async def _fetch_step_genes(api: StrategyAPI, step_id: int | None) -> list[str]:
    if step_id is None:
        return []
    try:
        gene_ids = await fetch_gene_ids_from_step(api, step_id=step_id)
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to fetch gene IDs from WDK step",
            step_id=step_id,
            error=str(exc),
        )
        return []
    else:
        logger.info(
            "Fetched gene IDs from WDK step",
            step_id=step_id,
            gene_count=len(gene_ids),
        )
        return gene_ids


async def _count_strategy_steps(api: StrategyAPI, strategy_id: int) -> int:
    try:
        strategy = await api.get_strategy(strategy_id)
        return len(strategy.steps)
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to count strategy steps",
            strategy_id=strategy_id,
            error=str(exc),
        )
        return 1


async def _extract_step_search_context(
    api: StrategyAPI,
    step_id: int,
    record_type: str | None,
) -> tuple[str | None, str | None, dict[str, ParamValue] | None]:
    """Extract the search name, record type, and parameters from a WDK step.

    Wire parameters need a search spec to decode, so parameters stay unset.
    """
    search_name: str | None = None
    parameters: dict[str, ParamValue] | None = None
    try:
        step = await api.find_step(step_id)
        sn = step.search_name
        if not sn.startswith("boolean_question_"):
            search_name = sn
            parameters = None
        if not record_type:
            rcn = step.record_class_name
            if rcn:
                record_type = (
                    rcn.split(".")[-1].replace("RecordClass", "").lower()
                    if "." in rcn
                    else "transcript"
                )
        logger.info(
            "Extracted search context from WDK step",
            step_id=step_id,
            search_name=search_name,
        )
    except VEuPathDBError as exc:
        logger.warning(
            "Failed to extract search context from step",
            step_id=step_id,
            error=str(exc),
        )
    return search_name, record_type, parameters
