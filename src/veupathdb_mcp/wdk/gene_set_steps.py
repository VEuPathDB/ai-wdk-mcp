"""WDK async helpers and context types for gene set operations."""

import hashlib
from dataclasses import dataclass
from typing import Literal

from cachetools import LRUCache
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import InputDatasetValue, ParamValue
from veupathdb.errors import ValidationError, WDKLoginRequiredError
from veupathdb.wdk import (
    NewStepSpec,
    StrategyAPI,
    WDKDatasetConfigIdList,
    WDKDatasetIdListContent,
    WDKSearchConfig,
    WDKStepTree,
    encode_params,
    get_strategy_api,
)

from veupathdb_mcp.catalog.searches import listed_record_type
from veupathdb_mcp.wdk.helpers import extract_record_ids
from veupathdb_mcp.wdk.step_report_filters import step_view_filters

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
    record_type = await listed_record_type(
        SearchContext(site_id, "transcript", "GeneByLocusTag")
    )
    api = get_strategy_api(site_id)
    config = WDKDatasetConfigIdList(
        source_type="idList",
        source_content=WDKDatasetIdListContent(ids=gene_ids),
    )
    dataset_id = await api.create_dataset(config)
    return (
        "GeneByLocusTag",
        {"ds_gene_ids": InputDatasetValue(dataset_id=str(dataset_id))},
        record_type,
    )


class StepTooLargeError(ValidationError):
    def __init__(self, step_id: int, limit: int) -> None:
        self.step_id = step_id
        self.limit = limit
        super().__init__(
            title="Step holds more records than the read allows",
            detail=f"step {step_id} holds more than {limit} records",
        )


def _require_a_positive_limit(limit: int) -> None:
    if limit < 1:
        msg = f"a step read limit must be at least 1, not {limit}"
        raise ValueError(msg)


async def fetch_gene_ids_from_step(
    api: StrategyAPI, *, step_id: int, limit: int
) -> list[str]:
    """Fetch gene IDs from a WDK step via the standard report endpoint.

    The read asks for one record more than ``limit``, and a step that holds
    more than ``limit`` records raises ``StepTooLargeError``.
    A transcript step answers one row per gene.
    """
    _require_a_positive_limit(limit)
    answer = await api.get_step_answer(
        step_id,
        attributes=["primary_key"],
        pagination={"offset": 0, "numRecords": limit + 1},
        view_filters=await step_view_filters(api, step_id),
    )
    if len(answer.records) > limit:
        raise StepTooLargeError(step_id, limit)
    return extract_record_ids(answer.records)


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

    search_name, params, record_type = await build_enrichment_params_from_gene_ids(
        site_id, gene_ids
    )
    api = get_strategy_api(site_id)
    created = await api.create_step(
        NewStepSpec(
            search_name=search_name,
            search_config=WDKSearchConfig(parameters=encode_params(params)),
        ),
        record_type,
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
