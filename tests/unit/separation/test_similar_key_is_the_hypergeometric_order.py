"""Among full-recall candidates, ranking by size is ranking by the genome tail."""

from math import comb

from tests._support.separation_sets import NEGATIVES

from veupathdb_mcp.controls import NegativeControls, PositiveControls
from veupathdb_mcp.separation import (
    Candidate,
    CandidateSource,
    MeasuredCandidate,
)
from veupathdb_mcp.separation.assemble import rank

POPULATION = 5300
POSITIVES = [f"PF3D7_03{i:05d}" for i in range(80)]


def _tail(size: int) -> float:
    """P(X >= 80) for 80 draws from a genome with ``size`` successes."""
    draws = len(POSITIVES)
    upper = min(size, draws)
    hits = sum(
        comb(size, x) * comb(POPULATION - size, draws - x)
        for x in range(draws, upper + 1)
    )
    return hits / comb(POPULATION, draws)


def _full_recall(candidate_id: str, size: int) -> MeasuredCandidate:
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
        positive=PositiveControls.filed(POSITIVES, set(POSITIVES)),
        negative=NegativeControls.filed(NEGATIVES, {NEGATIVES[0]}),
    )


def test_the_tail_orders_the_candidates_as_their_size_does() -> None:
    sizes = {"big": 4000, "small": 100, "mid": 400}
    candidates = [_full_recall(name, size) for name, size in sizes.items()]

    by_tail = sorted(sizes, key=lambda name: _tail(sizes[name]))
    by_rank = [m.candidate.id for m in rank(candidates)]

    assert by_tail == ["small", "mid", "big"]
    assert by_rank == by_tail
    assert _tail(100) < _tail(400) < _tail(4000)
