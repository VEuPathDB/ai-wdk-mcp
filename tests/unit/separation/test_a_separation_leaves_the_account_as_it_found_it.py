"""The steps a separation writes are deleted when a read fails before its strategy exists."""

import pytest
from tests._support.control_run_wdk import Faults, StepRunFakeAPI
from tests._support.separation_sets import NEGATIVES, POSITIVES
from veupathdb.domain.strategy import CombineOp
from veupathdb.errors import WDKError

from veupathdb_mcp.controls import CONTROLS_SEARCH, ControlsDataset
from veupathdb_mcp.separation import Candidate, CandidateSource, SeparationNode
from veupathdb_mcp.separation.budget import WdkCallBudget
from veupathdb_mcp.separation.measure import (
    ControlsUnderTest,
    measure_candidates,
    read_tree,
)


def _candidate(candidate_id: str) -> Candidate:
    return Candidate(
        id=candidate_id,
        search_name=f"GenesBy{candidate_id}",
        display_name=candidate_id,
        parameters={},
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
    )


def _controls() -> ControlsUnderTest:
    return ControlsUnderTest(
        positives=POSITIVES,
        negatives=NEGATIVES,
        dataset=ControlsDataset(
            search_name=CONTROLS_SEARCH,
            parameters={},
            record_type="transcript",
            id_count=len(POSITIVES) + len(NEGATIVES),
        ),
        strategy_name="control separation",
    )


async def test_a_tree_whose_combine_is_refused_leaves_no_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = SeparationNode(
        kind="combine",
        operator=CombineOp.UNION,
        inputs=[
            SeparationNode(kind="leaf", candidate_id="B"),
            SeparationNode(kind="leaf", candidate_id="C"),
        ],
    )
    site = StepRunFakeAPI([], faults=Faults(fail=frozenset({"create_combined_step"})))

    with pytest.raises(WDKError, match="create_combined_step refused"):
        await read_tree(site, tree, [_candidate("B"), _candidate("C")], _controls())

    assert site.holds() == ([], [])
    assert site.most_deletes_in_flight == 1


async def _ignore(update: object) -> None:
    del update


async def test_a_measurement_refused_before_its_strategy_leaves_no_step() -> None:
    site = StepRunFakeAPI([], faults=Faults(fail=frozenset({"create_strategy"})))

    measured, skipped = await measure_candidates(
        site,
        [_candidate("B")],
        _controls(),
        WdkCallBudget(limit=1000),
        _ignore,
    )

    assert (measured, [s.reason for s in skipped]) == ([], ["wdk_refused"])
    assert site.holds() == ([], [])
