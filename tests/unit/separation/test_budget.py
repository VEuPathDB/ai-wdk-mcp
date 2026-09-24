"""A run measures what its budget pays for and skips the rest as budget."""

import pytest
from tests._support.control_run_wdk import RunFakeAPI
from tests._support.separation_sets import NEGATIVES, POSITIVES

from veupathdb_mcp.controls import CONTROLS_SEARCH, ControlsDataset
from veupathdb_mcp.separation import (
    FIRST_INTERSECTION_REQUESTS,
    MAX_CRITERIA,
    MEASURE_REQUESTS,
    SEARCH_READ_REQUESTS,
    UPLOAD_REQUESTS,
    BudgetSpentError,
    Candidate,
    CandidateSource,
    SeparationUpdate,
    confirm_requests,
)
from veupathdb_mcp.separation.budget import WdkCallBudget
from veupathdb_mcp.separation.measure import ControlsUnderTest, measure_candidates

RESERVED = confirm_requests(MAX_CRITERIA)
EACH = MEASURE_REQUESTS + SEARCH_READ_REQUESTS
FIRST = EACH + FIRST_INTERSECTION_REQUESTS


def _candidates(count: int) -> list[Candidate]:
    return [
        Candidate(
            id=f"c{i}",
            search_name=f"GenesByFeature{i}",
            display_name=f"Feature {i}",
            parameters={},
            source=CandidateSource.CATALOG,
            basis="the site's catalog",
        )
        for i in range(1, count + 1)
    ]


def _controls() -> ControlsUnderTest:
    return ControlsUnderTest(
        positives=POSITIVES,
        negatives=NEGATIVES,
        dataset=ControlsDataset(
            search_name=CONTROLS_SEARCH, parameters={}, record_type="transcript"
        ),
        strategy_name="control separation",
    )


async def _ignore(update: SeparationUpdate) -> None:
    del update


async def test_ten_candidates_on_a_budget_for_three() -> None:
    limit = UPLOAD_REQUESTS + RESERVED + FIRST + 2 * EACH + EACH - 1
    budget = WdkCallBudget(limit=limit)
    budget.reserve(RESERVED)
    budget.charge(UPLOAD_REQUESTS)
    api = RunFakeAPI(answer_ids=(POSITIVES[0], NEGATIVES[0]))

    measured, skipped = await measure_candidates(
        api, _candidates(10), _controls(), budget, _ignore
    )

    assert [m.candidate.id for m in measured] == ["c1", "c2", "c3"]
    assert [(s.search_name, s.reason) for s in skipped] == [
        (f"GenesByFeature{i}", "budget") for i in range(4, 11)
    ]
    assert api.calls.count("create_strategy") == 3
    budget.release()
    budget.charge(confirm_requests(1))
    assert budget.spent <= budget.limit


async def test_each_measurement_files_every_control() -> None:
    budget = WdkCallBudget(limit=FIRST)
    api = RunFakeAPI(step_count=5012, answer_ids=(POSITIVES[0], NEGATIVES[3]))

    measured, _ = await measure_candidates(
        api, _candidates(1), _controls(), budget, _ignore
    )

    assert measured[0].result_size == 5012
    assert measured[0].positive.recovered_ids == [POSITIVES[0]]
    assert measured[0].positive.missed_ids == POSITIVES[1:]
    assert measured[0].negative.admitted_ids == [NEGATIVES[3]]
    assert budget.spent == FIRST


def test_a_charge_past_the_limit_is_refused() -> None:
    budget = WdkCallBudget(limit=10)
    budget.reserve(4)

    with pytest.raises(BudgetSpentError):
        budget.charge(7)
    assert budget.spent == 0


async def test_a_second_step_of_one_search_is_charged_the_measurement_alone() -> None:
    candidates = [
        Candidate(
            id=f"c{i}",
            search_name="GenesByFeature",
            display_name="Feature",
            parameters={},
            source=CandidateSource.CATALOG,
            basis="the site's catalog",
        )
        for i in (1, 2)
    ]
    budget = WdkCallBudget(limit=FIRST + MEASURE_REQUESTS)

    measured, skipped = await measure_candidates(
        RunFakeAPI(), candidates, _controls(), budget, _ignore
    )

    assert [m.candidate.id for m in measured] == ["c1", "c2"]
    assert skipped == []
    assert budget.spent == FIRST + MEASURE_REQUESTS
