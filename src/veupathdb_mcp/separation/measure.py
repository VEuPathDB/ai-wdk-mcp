"""Measure each candidate against the uploaded controls, and read an assembled tree."""

import asyncio
from dataclasses import dataclass

from veupathdb.domain.strategy import CombineOp
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import (
    CombinedStepSpec,
    NewStepSpec,
    StrategyAPI,
    WDKSearchConfig,
    WDKStepTree,
    encode_params,
)

from veupathdb_mcp.controls import (
    ControlsDataset,
    Intersection,
    IntersectionTarget,
    NegativeControls,
    PositiveControls,
    intersect_with_controls,
)
from veupathdb_mcp.separation.budget import (
    FIRST_INTERSECTION_REQUESTS,
    MEASURE_REQUESTS,
    SEARCH_READ_REQUESTS,
    WdkCallBudget,
)
from veupathdb_mcp.separation.eligibility import GENE_RECORD_CLASS
from veupathdb_mcp.separation.models import (
    Candidate,
    MeasuredCandidate,
    SeparationNode,
    SeparationProgress,
    SeparationUpdate,
    SkippedCandidate,
    SkipReason,
)
from veupathdb_mcp.wdk import describe_step_refusal

MAX_PARALLEL = 5
"""The measurements one run holds open on the site at once."""


@dataclass(frozen=True)
class ControlsUnderTest:
    """The resolved controls, the one dataset that holds them, and the strategy name."""

    positives: list[str]
    negatives: list[str]
    dataset: ControlsDataset
    strategy_name: str


class _NoCountError(Exception):
    """WDK built the target but answered no count for it."""


async def _leaf_step(api: StrategyAPI, candidate: Candidate) -> WDKStepTree:
    step = await api.create_step(
        NewStepSpec(
            search_name=candidate.search_name,
            search_config=WDKSearchConfig(
                parameters=encode_params(candidate.parameters)
            ),
            custom_name=candidate.display_name,
        ),
        record_type=GENE_RECORD_CLASS,
    )
    return WDKStepTree(step_id=step.id)


async def _intersect(
    api: StrategyAPI, tree: WDKStepTree, controls: ControlsUnderTest
) -> Intersection:
    return await intersect_with_controls(
        api,
        IntersectionTarget(tree=tree, record_type=GENE_RECORD_CLASS),
        controls.dataset,
        strategy_name=controls.strategy_name,
    )


async def _measure_one(
    api: StrategyAPI, candidate: Candidate, controls: ControlsUnderTest
) -> MeasuredCandidate:
    run = await _intersect(api, await _leaf_step(api, candidate), controls)
    if run.target_count is None:
        msg = "WDK answered no count for the step"
        raise _NoCountError(msg)
    return MeasuredCandidate(
        candidate=candidate,
        result_size=run.target_count,
        positive=PositiveControls.filed(controls.positives, run.returned_ids),
        negative=NegativeControls.filed(controls.negatives, run.returned_ids),
    )


def _measured_row(m: MeasuredCandidate) -> SeparationUpdate:
    c = m.candidate
    return SeparationUpdate(
        phase="measured",
        candidate_id=c.id,
        message=(
            f"{c.search_name}: {m.positive.intersection_count} of "
            f"{m.positive.controls_count} positives, {m.negative.intersection_count} "
            f"of {m.negative.controls_count} negatives, {m.result_size:,} genes"
        ),
        data={
            "search": c.search_name,
            "source": c.source.value,
            "recovered": m.positive.intersection_count,
            "admitted": m.negative.intersection_count,
            "size": m.result_size,
        },
    )


def _skipped(
    candidate: Candidate, reason: SkipReason, detail: str = ""
) -> SkippedCandidate:
    return SkippedCandidate(
        search_name=candidate.search_name,
        source=candidate.source,
        basis=candidate.basis,
        reason=reason,
        detail=detail,
    )


def _measure_charge(candidate: Candidate, stepped: set[str], *, first: bool) -> int:
    """One measurement, the first step of its search, and the first intersection."""
    charge = MEASURE_REQUESTS
    if candidate.search_name not in stepped:
        charge += SEARCH_READ_REQUESTS
    if first:
        charge += FIRST_INTERSECTION_REQUESTS
    return charge


async def measure_candidates(
    api: StrategyAPI,
    candidates: list[Candidate],
    controls: ControlsUnderTest,
    budget: WdkCallBudget,
    progress: SeparationProgress,
) -> tuple[list[MeasuredCandidate], list[SkippedCandidate]]:
    """Measure every candidate the budget pays for, in order; skip the rest as budget.

    A step WDK refuses is skipped with WDK's own words.
    """
    admitted: list[Candidate] = []
    unpaid: list[SkippedCandidate] = []
    stepped: set[str] = set()
    for candidate in candidates:
        charge = _measure_charge(candidate, stepped, first=not admitted)
        if budget.affords(charge):
            budget.charge(charge)
            admitted.append(candidate)
            stepped.add(candidate.search_name)
        else:
            unpaid.append(_skipped(candidate, "budget"))
    gate = asyncio.Semaphore(MAX_PARALLEL)
    measured: dict[str, MeasuredCandidate] = {}
    refused: dict[str, SkippedCandidate] = {}

    async def run(candidate: Candidate) -> None:
        async with gate:
            try:
                measured[candidate.id] = await _measure_one(api, candidate, controls)
            except (VEuPathDBError, _NoCountError) as exc:
                detail = describe_step_refusal(str(exc)) or str(exc)
                refused[candidate.id] = _skipped(candidate, "wdk_refused", detail)
                await progress(
                    SeparationUpdate(
                        phase="measured",
                        candidate_id=candidate.id,
                        message=f"{candidate.search_name}: skipped: WDK refused {detail}",
                        data={"search": candidate.search_name, "refused": detail},
                    )
                )
                return
        await progress(_measured_row(measured[candidate.id]))

    await asyncio.gather(*(run(candidate) for candidate in admitted))
    order = [c.id for c in admitted]
    return (
        [measured[cid] for cid in order if cid in measured],
        [refused[cid] for cid in order if cid in refused] + unpaid,
    )


async def _build(
    api: StrategyAPI, node: SeparationNode, by_id: dict[str, Candidate]
) -> WDKStepTree:
    match node:
        case SeparationNode(
            kind="combine", operator=CombineOp() as operator, inputs=[left, right]
        ):
            primary = await _build(api, left, by_id)
            secondary = await _build(api, right, by_id)
            combined = await api.create_combined_step(
                CombinedStepSpec(
                    primary_step_id=primary.step_id,
                    secondary_step_id=secondary.step_id,
                    boolean_operator=operator,
                    custom_name=operator.value,
                ),
                record_type=GENE_RECORD_CLASS,
            )
            return WDKStepTree(
                step_id=combined.id, primary_input=primary, secondary_input=secondary
            )
        case _:
            return await _leaf_step(api, by_id[str(node.candidate_id)])


async def read_tree(
    api: StrategyAPI,
    tree: SeparationNode,
    candidates: list[Candidate],
    controls: ControlsUnderTest,
) -> Intersection:
    """Build the assembled tree as steps and read its count and its controls from WDK."""
    by_id = {c.id: c for c in candidates}
    return await _intersect(api, await _build(api, tree, by_id), controls)
