"""A refused candidate keeps WDK's words, and the confirm read builds the whole tree."""

from tests._support.control_run_wdk import RunFakeAPI
from tests._support.separation_sets import NEGATIVES, POSITIVES
from tests._support.wdk_refusals import OWN_VALUE_REFUSAL
from veupathdb.domain.strategy import CombineOp
from veupathdb.errors import WDKError
from veupathdb.wdk import NewStepSpec, WDKIdentifier, WDKStepTree

from veupathdb_mcp.controls import CONTROLS_SEARCH, ControlsDataset
from veupathdb_mcp.separation import (
    Candidate,
    CandidateSource,
    SeparationNode,
    SeparationUpdate,
)
from veupathdb_mcp.separation.budget import WdkCallBudget
from veupathdb_mcp.separation.measure import (
    ControlsUnderTest,
    measure_candidates,
    read_tree,
)

_NO_COUNT = "the count is unavailable"


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
            search_name=CONTROLS_SEARCH, parameters={}, record_type="transcript"
        ),
        strategy_name="control separation",
    )


class _Refusing(RunFakeAPI):
    """A site that refuses the step of one search."""

    async def create_step(
        self, spec: NewStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        if spec.search_name == "GenesByBad":
            raise WDKError(OWN_VALUE_REFUSAL, status=422)
        return await super().create_step(spec, record_type, user_id)


class _Uncounted(RunFakeAPI):
    """A site that builds every step and answers no count."""

    async def get_step_count(self, step_id: int) -> int:
        raise WDKError(_NO_COUNT, status=500)


async def test_a_refused_step_is_skipped_with_wdk_s_words() -> None:
    rows: list[SeparationUpdate] = []

    async def progress(update: SeparationUpdate) -> None:
        rows.append(update)

    measured, skipped = await measure_candidates(
        _Refusing(),
        [_candidate("Bad"), _candidate("Good")],
        _controls(),
        WdkCallBudget(limit=100),
        progress,
    )

    assert [m.candidate.id for m in measured] == ["Good"]
    assert (skipped[0].search_name, skipped[0].reason) == ("GenesByBad", "wdk_refused")
    assert "Plasmodium berghei ANKA" in skipped[0].detail
    assert sorted(row.candidate_id or "" for row in rows) == ["Bad", "Good"]


async def test_a_step_without_a_count_is_skipped() -> None:
    async def ignore(update: SeparationUpdate) -> None:
        del update

    measured, skipped = await measure_candidates(
        _Uncounted(), [_candidate("A")], _controls(), WdkCallBudget(limit=100), ignore
    )

    assert measured == []
    assert skipped[0].detail == "WDK answered no count for the step"


async def test_the_confirm_read_builds_every_combine_in_order() -> None:
    tree = SeparationNode(
        kind="combine",
        operator=CombineOp.UNION,
        inputs=[
            SeparationNode(kind="leaf", candidate_id="B"),
            SeparationNode(kind="leaf", candidate_id="C"),
        ],
    )
    api = RunFakeAPI(step_count=900, answer_ids=(POSITIVES[0],))

    read = await read_tree(api, tree, [_candidate("B"), _candidate("C")], _controls())

    assert api.calls == [
        "create_step",
        "create_step",
        "create_combined_step",
        "create_step",
        "create_combined_step",
        "create_strategy",
        "get_step_count",
        "get_step_answer",
        "delete_strategy",
    ]
    assert [spec.search_name for spec in api.steps] == [
        "GenesByB",
        "GenesByC",
        CONTROLS_SEARCH,
    ]
    assert [c.boolean_operator for c in api.combines] == [
        CombineOp.UNION,
        CombineOp.INTERSECT,
    ]
    assert api.trees == [
        WDKStepTree(
            step_id=205,
            primary_input=WDKStepTree(
                step_id=203,
                primary_input=WDKStepTree(step_id=201),
                secondary_input=WDKStepTree(step_id=202),
            ),
            secondary_input=WDKStepTree(step_id=204),
        )
    ]
    assert (read.target_count, read.returned_ids) == (900, frozenset(POSITIVES[:1]))
