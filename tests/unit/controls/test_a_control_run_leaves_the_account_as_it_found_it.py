"""Every step and strategy a control run writes is deleted, whatever ends the run."""

import asyncio
from datetime import timedelta

import pytest
from structlog.testing import capture_logs
from tests._support.control_run_wdk import (
    TESTED_STEP,
    Faults,
    StepRunFakeAPI,
    gene_records,
    patch_step_run,
    wdk_time,
)
from veupathdb.errors import WDKError
from veupathdb.wdk import WDKStepTree

from veupathdb_mcp.controls import delete_temp_strategy, run_step_control_tests

TREE = WDKStepTree(
    step_id=4300,
    primary_input=WDKStepTree(step_id=TESTED_STEP),
    secondary_input=WDKStepTree(step_id=4250),
)


def _site(
    monkeypatch: pytest.MonkeyPatch,
    fail: frozenset[str] = frozenset(),
    hold: frozenset[str] = frozenset(),
    lose: frozenset[str] = frozenset(),
) -> StepRunFakeAPI:
    return patch_step_run(
        monkeypatch,
        StepRunFakeAPI(
            gene_records("PF3D7_0100100"),
            strategy_tree=TREE,
            faults=Faults(fail=fail, hold=hold, lose=lose),
        ),
    )


async def _run() -> None:
    await run_step_control_tests("plasmodb", TESTED_STEP, ["PF3D7_0100100"])


async def test_a_finished_run_holds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    site = _site(monkeypatch)

    await _run()

    assert site.holds() == ([], [])
    assert site.deleted == [8000]


@pytest.mark.parametrize(
    "refused", ["create_step", "create_combined_step", "create_strategy"]
)
async def test_a_refused_write_leaves_nothing_behind(
    monkeypatch: pytest.MonkeyPatch, refused: str
) -> None:
    site = _site(monkeypatch, fail=frozenset({refused}))

    with pytest.raises(WDKError, match=f"{refused} refused"):
        await _run()

    assert site.holds() == ([], [])
    assert site.most_deletes_in_flight == 1


async def test_a_run_cancelled_while_its_strategy_is_written_holds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch, hold=frozenset({"create_strategy"}))
    run = asyncio.create_task(_run())
    async with asyncio.timeout(5):
        await site.reached["create_strategy"].wait()

    run.cancel()
    site.release["create_strategy"].set()

    with pytest.raises(asyncio.CancelledError):
        await run
    assert site.holds() == ([], [])
    assert site.deleted == [8000]


async def test_a_refused_cleanup_is_logged_and_the_first_error_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch, fail=frozenset({"create_combined_step", "delete_step"}))

    with capture_logs() as logs, pytest.raises(WDKError, match="create_combined_step"):
        await _run()

    assert site.unattached != []
    assert {entry["event"] for entry in logs} >= {"Failed to delete a control-run step"}


async def test_a_second_cancellation_does_not_stop_the_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch, hold=frozenset({"create_strategy", "delete_strategy"}))
    run = asyncio.create_task(_run())
    async with asyncio.timeout(5):
        await site.reached["create_strategy"].wait()
    run.cancel()
    site.release["create_strategy"].set()
    async with asyncio.timeout(5):
        await site.reached["delete_strategy"].wait()

    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    site.release["delete_strategy"].set()

    async with asyncio.timeout(5):
        await site.strategy_deleted.wait()
    assert site.holds() == ([], [])
    assert site.deleted == [8000]


async def test_a_strategy_whose_answer_was_lost_is_swept_once_it_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch, lose=frozenset({"create_strategy"}))
    with pytest.raises(WDKError, match="answer to create_strategy was lost"):
        await _run()
    assert site.holds()[1] == [8000]

    site.faults = Faults()
    site.strategy_created[8000] = wdk_time(timedelta(days=3))
    site.calls.clear()
    await _run()

    assert site.holds() == ([], [])
    assert site.deleted == [8000, 8001]
    assert site.calls.index("list_strategies") < site.calls.index("create_dataset")


async def test_a_run_without_controls_sweeps_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch)

    await run_step_control_tests("plasmodb", TESTED_STEP)

    assert "list_strategies" not in site.calls


class _UnreachableAccount:
    async def delete_strategy(
        self, strategy_id: int, user_id: str | None = None
    ) -> None:
        msg = "the site did not answer"
        raise OSError(msg)


async def test_a_strategy_delete_the_site_never_answers_is_logged() -> None:
    with capture_logs() as logs:
        await delete_temp_strategy(_UnreachableAccount(), 8000)

    assert [entry["temp_strategy_id"] for entry in logs] == [8000]


async def test_a_concurrent_runs_fresh_strategy_survives_the_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch)
    site.seed_strategy(7001, "control test 5f2a9c", wdk_time(timedelta(minutes=2)))
    site.seed_strategy(7002, "control test 0be311", wdk_time(timedelta(days=3)))
    site.seed_strategy(7003, "control test 9d4e70", "")

    await _run()

    assert site.holds()[1] == [7001, 7003]
    assert 7002 in site.deleted


async def test_each_run_names_its_strategy_uniquely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch)

    await _run()
    await _run()

    first, second = site.created_strategy_names
    assert first != second
    assert first.startswith("control test ")
    assert second.startswith("control test ")
