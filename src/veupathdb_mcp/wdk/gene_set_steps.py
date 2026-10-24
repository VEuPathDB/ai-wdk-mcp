"""WDK async helpers and context types for gene set operations."""

import hashlib
from dataclasses import dataclass
from typing import Literal

from cachetools import LRUCache
from pydantic import BaseModel, ConfigDict
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
type IdListRecordType = Literal["transcript", "group"]

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


@dataclass(frozen=True, slots=True)
class IdListSearch:
    record_type: str
    search_name: str
    param_name: str
    exact: bool

    def distinct(self, ids: list[str]) -> list[str]:
        if not self.exact:
            return ids
        first: dict[str, str] = {}
        for one in ids:
            first.setdefault(one.casefold(), one)
        return list(first.values())


ID_LIST_SEARCHES: dict[IdListRecordType, IdListSearch] = {
    "transcript": IdListSearch(
        "transcript", "GeneByLocusTag", "ds_gene_ids", exact=False
    ),
    "group": IdListSearch("group", "GroupsByNameList", "group_names", exact=True),
}


class IdListStepCountError(ValidationError):
    def __init__(self, search_name: str, uploaded: int, counted: int) -> None:
        self.search_name = search_name
        self.uploaded = uploaded
        self.counted = counted
        super().__init__(
            title="The step does not hold the ids uploaded",
            detail=(
                f"{uploaded} ids were uploaded to {search_name} and its step holds "
                f"{counted} records, so the step is not the list. An id the site does "
                "not hold adds no record, and an id of an earlier release adds each "
                "current record it maps to."
            ),
        )


class IdListDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    search_name: str
    param_name: str
    dataset_id: int
    record_type: str

    def params(self) -> dict[str, ParamValue]:
        return {self.param_name: InputDatasetValue(dataset_id=str(self.dataset_id))}


class EmptyIdListError(ValidationError):
    def __init__(self, search_name: str) -> None:
        self.search_name = search_name
        super().__init__(
            title="The id list is empty",
            detail=f"{search_name} takes a list of at least one id.",
        )


async def id_list_dataset(
    site_id: str, ids: list[str], search: IdListSearch
) -> IdListDataset:
    record_type = await listed_record_type(
        SearchContext(site_id, search.record_type, search.search_name)
    )
    api = get_strategy_api(site_id)
    config = WDKDatasetConfigIdList(
        source_type="idList",
        source_content=WDKDatasetIdListContent(ids=ids),
    )
    return IdListDataset(
        search_name=search.search_name,
        param_name=search.param_name,
        dataset_id=await api.create_dataset(config),
        record_type=record_type,
    )


async def id_list_params(
    site_id: str, ids: list[str], search: IdListSearch
) -> tuple[str, dict[str, ParamValue], str]:
    dataset = await id_list_dataset(site_id, ids, search)
    return dataset.search_name, dataset.params(), dataset.record_type


async def build_enrichment_params_from_gene_ids(
    site_id: str,
    gene_ids: list[str],
) -> tuple[str, dict[str, ParamValue], str]:
    """Create a WDK dataset from gene IDs and return enrichment parameters.

    The dataset is temporary and is addressed by a locus-tag search.
    """
    return await id_list_params(site_id, gene_ids, ID_LIST_SEARCHES["transcript"])


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


def frozen_step_cache_key(
    account: str,
    site_id: str,
    gene_ids: list[str],
    *,
    record_type: IdListRecordType = "transcript",
) -> str:
    """Key a materialized step by the account that holds it and its membership.

    Membership is a set, so order does not make a new step. A step id names a
    step in one account on one site, so both are part of the key.
    """
    digest = hashlib.sha256("\n".join(sorted(set(gene_ids))).encode()).hexdigest()
    return f"{account}:{site_id}:{record_type}:{digest}"


async def frozen_step_id(
    site_id: str,
    gene_ids: list[str],
    *,
    strategy_name: str = DEFAULT_GENE_SET_STRATEGY_NAME,
    record_type: IdListRecordType = "transcript",
) -> int | None:
    """A WDK step holding exactly ``gene_ids``, or ``None`` when there are none.

    A step browsed through the search it came from shows whatever that search
    returns now. Materializing the ids gives WDK something to report
    attributes from without letting it decide who is in the set.
    ``strategy_name`` names the internal strategy that holds the step. A call
    that carries no WDK credential is refused, because no account holds it.
    """
    search = ID_LIST_SEARCHES[record_type]
    gene_ids = search.distinct(gene_ids)
    if not gene_ids:
        return None
    key = frozen_step_cache_key(
        _calling_account(), site_id, gene_ids, record_type=record_type
    )
    cached: int | None = _FROZEN_STEPS.get(key)
    if cached is not None:
        return cached

    dataset = await id_list_dataset(site_id, gene_ids, search)
    api = get_strategy_api(site_id)
    held = await _held_step(api, dataset, strategy_name)
    try:
        await _require_the_ids(api, held, search, len(gene_ids))
    except IdListStepCountError:
        await api.delete_strategy(held.strategy_id)
        raise
    _FROZEN_STEPS[key] = held.step_id
    return held.step_id


async def counted_id_list(
    site_id: str,
    ids: list[str],
    *,
    record_type: IdListRecordType,
    strategy_name: str = DEFAULT_GENE_SET_STRATEGY_NAME,
) -> IdListDataset:
    _calling_account()
    search = ID_LIST_SEARCHES[record_type]
    ids = search.distinct(ids)
    if not ids:
        raise EmptyIdListError(search.search_name)
    dataset = await id_list_dataset(site_id, ids, search)
    api = get_strategy_api(site_id)
    held = await _held_step(api, dataset, strategy_name)
    try:
        await _require_the_ids(api, held, search, len(ids))
    finally:
        await api.delete_strategy(held.strategy_id)
    return dataset


@dataclass(frozen=True, slots=True)
class _HeldStep:
    step_id: int
    strategy_id: int


async def _held_step(
    api: StrategyAPI, dataset: IdListDataset, strategy_name: str
) -> _HeldStep:
    created = await api.create_step(
        NewStepSpec(
            search_name=dataset.search_name,
            search_config=WDKSearchConfig(parameters=encode_params(dataset.params())),
        ),
        dataset.record_type,
    )
    # WDK refuses to run a step that belongs to no strategy, so the step is
    # held by an internal one that never appears in the user's workspace.
    strategy = await api.create_strategy(
        step_tree=WDKStepTree(step_id=created.id),
        name=strategy_name,
        description=None,
        is_internal=True,
    )
    return _HeldStep(step_id=created.id, strategy_id=strategy.id)


async def _require_the_ids(
    api: StrategyAPI, held: _HeldStep, search: IdListSearch, uploaded: int
) -> None:
    if not search.exact:
        return
    counted = await api.get_step_count(held.step_id)
    if counted != uploaded:
        raise IdListStepCountError(search.search_name, uploaded, counted)
