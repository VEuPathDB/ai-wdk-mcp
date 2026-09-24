"""A search control test uploads one dataset and reads both sets from one intersection."""

import pytest
from tests._support.control_run_wdk import RunFakeAPI, patch_control_account

from veupathdb_mcp.controls import (
    CONTROLS_PARAM,
    CONTROLS_SEARCH,
    IntersectionConfig,
    run_positive_negative_controls,
)

POSITIVES = ["PF3D7_0100100", "PF3D7_0100200", "PF3D7_0100300"]
NEGATIVES = ["PF3D7_0200100", "PF3D7_0200200"]

ONE_INTERSECTION = [
    "list_strategies",
    "get_search_details",
    "create_dataset",
    "create_step",
    "create_step",
    "create_combined_step",
    "create_strategy",
    "get_step_count",
    "get_step_answer",
    "delete_strategy",
]


def _config() -> IntersectionConfig:
    return IntersectionConfig(
        site_id="plasmodb",
        record_type="transcript",
        target_search_name="GenesByMolecularWeight",
        target_parameters={},
        controls_search_name=CONTROLS_SEARCH,
        controls_param_name=CONTROLS_PARAM,
    )


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> RunFakeAPI:
    returned = (POSITIVES[0], POSITIVES[2], NEGATIVES[1], "PF3D7_0900900")
    return patch_control_account(monkeypatch, RunFakeAPI(answer_ids=returned))


async def test_both_sets_cost_ten_requests(account: RunFakeAPI) -> None:
    """The cleanup list, one dataset, one param read and one intersection."""
    await run_positive_negative_controls(
        _config(), positive_controls=POSITIVES, negative_controls=NEGATIVES
    )

    assert account.calls == ONE_INTERSECTION


async def test_one_dataset_holds_the_positives_and_the_negatives(
    account: RunFakeAPI,
) -> None:
    await run_positive_negative_controls(
        _config(), positive_controls=POSITIVES, negative_controls=NEGATIVES
    )

    assert account.datasets == [POSITIVES + NEGATIVES]


async def test_each_id_is_filed_from_the_one_answer(account: RunFakeAPI) -> None:
    result = await run_positive_negative_controls(
        _config(), positive_controls=POSITIVES, negative_controls=NEGATIVES
    )

    assert result.positive is not None
    assert result.positive.recovered_ids == [POSITIVES[0], POSITIVES[2]]
    assert result.positive.missed_ids == [POSITIVES[1]]
    assert result.negative is not None
    assert result.negative.admitted_ids == [NEGATIVES[1]]
    assert result.negative.excluded_ids == [NEGATIVES[0]]
    assert result.target.step_id == 201
    assert result.target.estimated_size == 12
