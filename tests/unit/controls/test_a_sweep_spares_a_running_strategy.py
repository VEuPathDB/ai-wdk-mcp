"""A sweep deletes an internal strategy of its prefix only once no run can still hold it."""

from datetime import timedelta

import pytest
from tests._support.control_run_wdk import (
    FakeCleanupAPI,
    RunFakeAPI,
    patch_control_run,
    wdk_time,
)
from veupathdb.wdk import WDKStrategySummary, tag_internal_wdk_strategy_name

from veupathdb_mcp.controls import IntersectionConfig, run_positive_negative_controls
from veupathdb_mcp.controls.control_helpers import (
    LEFTOVER_AGE,
    cleanup_internal_control_test_strategies,
    stale_leftover_ids,
)
from veupathdb_mcp.server import CONTROL_TESTS_MAX_CALL_SECONDS


def _internal(strategy_id: int, name: str, created_time: str) -> WDKStrategySummary:
    return WDKStrategySummary(
        strategy_id=strategy_id,
        name=tag_internal_wdk_strategy_name(name),
        root_step_id=1,
        created_time=created_time,
    )


ACCOUNT = [
    _internal(1, "control test 5f2a9c", wdk_time(timedelta(minutes=2))),
    _internal(2, "control test 0be311", wdk_time(timedelta(days=3))),
    _internal(3, "control test 9d4e70", ""),
    _internal(4, "control test 77aa01", "yesterday"),
    _internal(5, "Pathfinder gene set 1", wdk_time(timedelta(days=3))),
    WDKStrategySummary(
        strategy_id=6,
        name="control test",
        root_step_id=1,
        created_time=wdk_time(timedelta(days=3)),
    ),
]


def test_the_age_outlasts_any_run_and_any_clock_zone() -> None:
    assert timedelta(seconds=CONTROL_TESTS_MAX_CALL_SECONDS, hours=26) < LEFTOVER_AGE


def test_only_a_stale_internal_strategy_of_the_prefix_is_a_leftover() -> None:
    assert stale_leftover_ids(ACCOUNT, "control test") == [2]


def test_wdks_fractional_seconds_are_read() -> None:
    stale = wdk_time(timedelta(days=3)) + ".123456"

    assert stale_leftover_ids(
        [_internal(9, "control test a", stale)], "control test"
    ) == [9]


def _config() -> IntersectionConfig:
    return IntersectionConfig(
        site_id="plasmodb",
        record_type="transcript",
        target_search_name="GenesByMolecularWeight",
        target_parameters={},
        controls_search_name="GeneByLocusTag",
        controls_param_name="ds_gene_ids",
    )


async def test_the_public_cleanup_keeps_the_same_rule() -> None:
    api = FakeCleanupAPI()

    await cleanup_internal_control_test_strategies(api, ACCOUNT, _config())

    assert api.deleted == [2]


class _Account(RunFakeAPI):
    async def list_strategies(self) -> list[WDKStrategySummary]:
        self.calls.append("list_strategies")
        return ACCOUNT


async def test_the_search_runner_sweeps_by_the_same_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = patch_control_run(monkeypatch, _Account())

    await run_positive_negative_controls(_config(), positive_controls=["PF3D7_0100100"])

    assert api.deleted[0] == 2
    assert 1 not in api.deleted
    assert api.created_strategy_names[0].startswith("control test ")
