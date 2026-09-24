"""Measured candidates built from the control ids each one returned."""

from __future__ import annotations

from veupathdb.domain.strategy import CombineOp

from veupathdb_mcp.controls import NegativeControls, PositiveControls
from veupathdb_mcp.separation import (
    Candidate,
    CandidateSource,
    MeasuredCandidate,
    SeparationNode,
)

POSITIVES = [f"PF3D7_01000{i:02d}" for i in range(10)]
NEGATIVES = [f"PF3D7_02000{i:02d}" for i in range(8)]


def measured(
    candidate_id: str,
    recovered: range | list[int],
    admitted: range | list[int],
    size: int,
) -> MeasuredCandidate:
    """A candidate that returned these positive and negative indices in ``size`` genes."""
    return MeasuredCandidate(
        candidate=Candidate(
            id=candidate_id,
            search_name=f"GenesBy{candidate_id}",
            display_name=candidate_id,
            parameters={},
            source=CandidateSource.CATALOG,
            basis="the site's catalog",
        ),
        result_size=size,
        positive=PositiveControls.filed(POSITIVES, {POSITIVES[i] for i in recovered}),
        negative=NegativeControls.filed(NEGATIVES, {NEGATIVES[i] for i in admitted}),
    )


def moves(node: SeparationNode | None) -> list[tuple[CombineOp | None, str]]:
    """A left-deep tree as the moves that built it: the first leaf, then each combine."""
    if node is None:
        return []
    if node.kind == "leaf":
        return [(None, str(node.candidate_id))]
    left, right = node.inputs
    return [*moves(left), (node.operator, str(right.candidate_id))]
