"""WDK async helpers and context types for gene set operations."""

import hashlib
from dataclasses import dataclass
from typing import Literal

from cachetools import LRUCache
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.domain.parameters.values import InputDatasetValue, ParamValue
from veupathdb.errors import VEuPathDBError, WDKLoginRequiredError
from veupathdb.logging import get_logger
from veupathdb.wdk.factory import (
    get_strategy_api,
)
from veupathdb.wdk.strategy_api.api import StrategyAPI
from veupathdb.wdk.value_decoding import encode_params
from veupathdb.wdk.wdk_models import (
    NewStepSpec,
    WDKDatasetConfigIdList,
    WDKDatasetIdListContent,
    WDKSearchConfig,
    WDKStepTree,
)

from veupathdb_mcp.wdk.helpers import extract_record_ids

logger = get_logger(__name__)

SetOperation = Literal["intersect", "union", "minus"]

DEFAULT_GENE_SET_STRATEGY_NAME = "gene set"

_FROZEN_STEPS: LRUCache[str, int] = LRUCache(maxsize=64)


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


async def fetch_gene_ids_from_step(
    api: StrategyAPI, *, step_id: int, limit: int | None = None
) -> list[str]:
    """Fetch gene IDs from a WDK step via the standard report endpoint.

    ``limit`` asks for one id more than the bound, so a caller can tell a step
    that fits from one that does not. None asks for every id the step holds.
    """
    answer = await api.get_step_answer(
        step_id,
        attributes=["primary_key"],
        pagination={"offset": 0, "numRecords": -1 if limit is None else limit + 1},
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


def _calling_account() -> str:
    """The account a WDK write of this call lands in, named without its token.

    WDK reads the account from the request's own token, so the token is what
    tells two callers apart. The digest keeps the credential out of the key.
    """
    token = veupathdb_auth_token_ctx.get()
    if not token:
        raise WDKLoginRequiredError
    return hashlib.sha256(token.encode()).hexdigest()


def frozen_step_cache_key(account: str, site_id: str, gene_ids: list[str]) -> str:
    """Key a materialized step by the account that holds it and its membership.

    Membership is a set, so order does not make a new step. A step id names a
    step in one account on one site, so both are part of the key.
    """
    digest = hashlib.sha256("\n".join(sorted(set(gene_ids))).encode()).hexdigest()
    return f"{account}:{site_id}:{digest}"


async def frozen_step_id(
    site_id: str,
    gene_ids: list[str],
    record_type: str,
    *,
    strategy_name: str = DEFAULT_GENE_SET_STRATEGY_NAME,
) -> int | None:
    """A WDK step holding exactly ``gene_ids``, or ``None`` when there are none.

    A step browsed through the search it came from shows whatever that search
    returns now. Materializing the ids gives WDK something to report
    attributes from without letting it decide who is in the set.
    ``strategy_name`` names the internal strategy that holds the step. A call
    that carries no WDK credential is refused, because no account holds it.
    """
    if not gene_ids:
        return None
    key = frozen_step_cache_key(_calling_account(), site_id, gene_ids)
    cached: int | None = _FROZEN_STEPS.get(key)
    if cached is not None:
        return cached

    (
        search_name,
        params,
        dataset_record_type,
    ) = await build_enrichment_params_from_gene_ids(site_id, gene_ids)
    api = get_strategy_api(site_id)
    created = await api.create_step(
        NewStepSpec(
            search_name=search_name,
            search_config=WDKSearchConfig(parameters=encode_params(params)),
        ),
        record_type or dataset_record_type,
    )
    # WDK refuses to run a step that belongs to no strategy, so the step is
    # held by an internal one that never appears in the user's workspace.
    await api.create_strategy(
        step_tree=WDKStepTree(step_id=created.id),
        name=strategy_name,
        description=None,
        is_internal=True,
    )
    _FROZEN_STEPS[key] = created.id
    return created.id
