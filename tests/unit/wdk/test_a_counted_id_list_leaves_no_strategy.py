from collections.abc import Iterator

import pytest
from tests._support.enrichment_wdk import FakeStrategyAPI, wdk
from tests._support.listed_searches import list_searches
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import WDKError, WDKLoginRequiredError
from veupathdb.wdk import WDKIdentifier, WDKStepTree

from veupathdb_mcp.wdk import (
    EmptyIdListError,
    IdListDataset,
    IdListStepCountError,
    counted_id_list,
    gene_set_steps,
)

__all__ = ["wdk"]

_FAILED = "the site failed"
GROUPS = ["OG8_0000011", "OG8_0000003", "OGR8r1_0000039"]


@pytest.fixture(autouse=True)
def account(wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    del wdk
    gene_set_steps._FROZEN_STEPS.clear()
    list_searches(monkeypatch, {"group": ["GroupsByNameList"]})
    reset = veupathdb_auth_token_ctx.set("registered-token")
    yield
    veupathdb_auth_token_ctx.reset(reset)


async def test_a_counted_list_keeps_its_dataset_and_deletes_its_strategy(
    wdk: FakeStrategyAPI,
) -> None:
    dataset = await counted_id_list("orthomcl", GROUPS, record_type="group")

    assert dataset == IdListDataset(
        search_name="GroupsByNameList",
        param_name="group_names",
        dataset_id=4242,
        record_type="group",
    )
    assert wdk.datasets == [GROUPS]
    assert wdk.calls == [
        "create_dataset",
        "create_step",
        "create_strategy",
        "get_step_count",
        "delete_strategy",
    ]
    assert wdk.deleted == [202]
    assert gene_set_steps._FROZEN_STEPS == {}


async def test_a_list_the_step_counts_otherwise_is_refused_and_its_strategy_deleted(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def mapped(step_id: int, user_id: str | None = None) -> int:
        del step_id, user_id
        return len(GROUPS) + 1

    monkeypatch.setattr(wdk, "get_step_count", mapped)

    with pytest.raises(IdListStepCountError) as refused:
        await counted_id_list("orthomcl", GROUPS, record_type="group")

    assert (refused.value.uploaded, refused.value.counted) == (3, 4)
    assert wdk.deleted == [202]
    assert gene_set_steps._FROZEN_STEPS == {}


async def test_a_count_that_fails_still_deletes_the_strategy(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(step_id: int, user_id: str | None = None) -> int:
        del step_id, user_id
        raise WDKError(_FAILED, status=500)

    monkeypatch.setattr(wdk, "get_step_count", failing)

    with pytest.raises(WDKError):
        await counted_id_list("orthomcl", GROUPS, record_type="group")

    assert wdk.deleted == [202]


async def test_a_strategy_that_was_never_created_is_not_deleted(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(
        *,
        step_tree: WDKStepTree,
        name: str,
        description: str | None = None,
        is_internal: bool = False,
    ) -> WDKIdentifier:
        del step_tree, name, description, is_internal
        raise WDKError(_FAILED, status=422)

    monkeypatch.setattr(wdk, "create_strategy", refused)

    with pytest.raises(WDKError):
        await counted_id_list("orthomcl", GROUPS, record_type="group")

    assert wdk.deleted == []
    assert "get_step_count" not in wdk.calls


async def test_group_ids_that_differ_only_in_case_are_counted_once(
    wdk: FakeStrategyAPI,
) -> None:
    spelled = ["OG8_0000011", "og8_0000011", "OGR8r1_0000039"]

    await counted_id_list("orthomcl", spelled, record_type="group")

    assert wdk.datasets == [["OG8_0000011", "OGR8r1_0000039"]]
    assert wdk.deleted == [202]


async def test_an_empty_list_writes_nothing(wdk: FakeStrategyAPI) -> None:
    with pytest.raises(EmptyIdListError):
        await counted_id_list("orthomcl", [], record_type="group")

    assert wdk.calls == []


async def test_a_call_that_names_no_account_writes_nothing(
    wdk: FakeStrategyAPI,
) -> None:
    reset = veupathdb_auth_token_ctx.set(None)
    try:
        with pytest.raises(WDKLoginRequiredError):
            await counted_id_list("orthomcl", GROUPS, record_type="group")
    finally:
        veupathdb_auth_token_ctx.reset(reset)

    assert wdk.calls == []
