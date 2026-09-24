"""The boolean the measured sets assemble by direction, and the gaps it leaves.

A recovering candidate covers and intersects, an excluding one is subtracted,
and one that informs neither way never enters a tree. Set algebra on the
control ids predicts each combine and only chooses; the confirm read of the
assembled tree is what a run reports.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from veupathdb.domain.strategy import CombineOp

from veupathdb_mcp.controls import NegativeControls, PositiveControls
from veupathdb_mcp.separation.budget import MAX_CRITERIA
from veupathdb_mcp.separation.models import (
    MeasuredCandidate,
    SeparationMode,
    SeparationNode,
    informs,
)


@dataclass(frozen=True)
class Assembly:
    """The assembled tree and the controls the measured sets predict it returns.

    ``capped`` is true when the tree reached ``MAX_CRITERIA`` with a gap left.
    """

    tree: SeparationNode | None
    recovered: frozenset[str]
    admitted: frozenset[str]
    capped: bool = False


def _recovered(m: MeasuredCandidate) -> frozenset[str]:
    return frozenset(m.positive.recovered_ids)


def _admitted(m: MeasuredCandidate) -> frozenset[str]:
    return frozenset(m.negative.admitted_ids)


def rank(measured: Iterable[MeasuredCandidate]) -> list[MeasuredCandidate]:
    """Most positives first, then fewest negatives, then the smallest result.

    A run tests one negative list, so the false-positive rate orders as the
    admitted count does.
    """
    return sorted(
        measured,
        key=lambda m: (-len(_recovered(m)), len(_admitted(m)), m.result_size),
    )


def leaf_ids(node: SeparationNode | None) -> list[str]:
    """The candidate ids of a tree's leaves, left to right."""
    if node is None:
        return []
    if node.kind == "leaf":
        return [str(node.candidate_id)]
    return [cid for child in node.inputs for cid in leaf_ids(child)]


@dataclass
class _Tree:
    node: SeparationNode
    recovered: frozenset[str]
    admitted: frozenset[str]
    used: list[str] = field(default_factory=list)

    @classmethod
    def start(cls, m: MeasuredCandidate) -> "_Tree":
        return cls(
            node=SeparationNode(kind="leaf", candidate_id=m.candidate.id),
            recovered=_recovered(m),
            admitted=_admitted(m),
            used=[m.candidate.id],
        )

    def add(self, operator: CombineOp, m: MeasuredCandidate) -> None:
        leaf = SeparationNode(kind="leaf", candidate_id=m.candidate.id)
        self.node = SeparationNode(
            kind="combine", operator=operator, inputs=[self.node, leaf]
        )
        self.used.append(m.candidate.id)
        if operator == CombineOp.UNION:
            self.recovered |= _recovered(m)
            self.admitted |= _admitted(m)
        elif operator == CombineOp.INTERSECT:
            self.recovered &= _recovered(m)
            self.admitted &= _admitted(m)
        else:
            self.recovered -= _recovered(m)
            self.admitted -= _admitted(m)

    def full(self) -> bool:
        return len(self.used) >= MAX_CRITERIA


def _cover(
    ranked: list[MeasuredCandidate], positives: frozenset[str]
) -> tuple[_Tree | None, bool]:
    """Every positive the measured sets can recover, by one candidate or a union."""
    whole = [m for m in ranked if _recovered(m) >= positives]
    if whole:
        return _Tree.start(whole[0]), False
    tree: _Tree | None = None
    covered: frozenset[str] = frozenset()
    while covered != positives:
        if tree is not None and tree.full():
            return tree, True
        unused = [m for m in ranked if tree is None or m.candidate.id not in tree.used]
        best = max(
            unused,
            key=lambda m: (
                len(_recovered(m) - covered),
                -len(_admitted(m)),
                -m.result_size,
            ),
            default=None,
        )
        if best is None or not _recovered(best) - covered:
            break
        if tree is None:
            tree = _Tree.start(best)
        else:
            tree.add(CombineOp.UNION, best)
        covered = tree.recovered
    return tree, False


def _best_move(
    tree: _Tree,
    recovering: list[MeasuredCandidate],
    excluding: list[MeasuredCandidate],
) -> tuple[CombineOp, MeasuredCandidate, int] | None:
    """The move that removes the most negatives and keeps every recovered positive.

    A tie goes to an intersection, then to the smaller result.
    """
    moves = [
        (CombineOp.INTERSECT, m, len(tree.admitted - _admitted(m)))
        for m in recovering
        if m.candidate.id not in tree.used and _recovered(m) >= tree.recovered
    ]
    moves += [
        (CombineOp.MINUS, m, len(tree.admitted & _admitted(m)))
        for m in excluding
        if m.candidate.id not in tree.used and not _recovered(m) & tree.recovered
    ]
    return max(
        moves,
        key=lambda move: (
            move[2],
            move[0] == CombineOp.INTERSECT,
            -move[1].result_size,
        ),
        default=None,
    )


def _refine(
    tree: _Tree,
    recovering: list[MeasuredCandidate],
    excluding: list[MeasuredCandidate],
) -> bool:
    """Remove negatives, most first. True when the cap stops it with one left."""
    while tree.admitted:
        if tree.full():
            return True
        move = _best_move(tree, recovering, excluding)
        if move is None or move[2] == 0:
            return False
        tree.add(move[0], move[1])
    return False


def assemble(
    measured: list[MeasuredCandidate], mode: SeparationMode, positives: list[str]
) -> Assembly:
    """COVER the positives with recovering candidates, then remove negatives.

    Both modes intersect with recovering candidates; exact mode also subtracts
    excluding ones.
    """
    recovering = rank(m for m in measured if m.informs == "recovering")
    excluding = (
        rank(m for m in measured if m.informs == "excluding") if mode == "exact" else []
    )
    tree, capped = _cover(recovering, frozenset(positives))
    if tree is None:
        return Assembly(tree=None, recovered=frozenset(), admitted=frozenset())
    if not capped:
        capped = _refine(tree, recovering, excluding)
    return Assembly(
        tree=tree.node,
        recovered=tree.recovered,
        admitted=tree.admitted,
        capped=capped,
    )


def _ids(ids: Iterable[str]) -> str:
    listed = sorted(ids)
    if len(listed) == 1:
        return listed[0]
    return f"{', '.join(listed[:-1])} or {listed[-1]}"


def _held(measured: Iterable[MeasuredCandidate]) -> frozenset[str]:
    return frozenset().union(*(_recovered(m) for m in measured))


def _missed_sentences(
    assembly: Assembly,
    positive: PositiveControls,
    measured: list[MeasuredCandidate],
) -> list[str]:
    missed = frozenset(positive.missed_ids)
    reachable = _held(measured)
    recovering = _held(m for m in measured if m.informs == "recovering")
    sentences: list[str] = []
    if nobody := missed - reachable:
        sentences.append(f"No measured criterion recovers {_ids(nobody)}.")
    if by_chance := (missed & reachable) - recovering:
        sentences.append(
            "Only criteria that do not return the positives above chance "
            f"recover {_ids(by_chance)}."
        )
    if dropped := (missed & recovering) - assembly.recovered:
        sentences.append(
            f"The strategy holds the limit of {MAX_CRITERIA} criteria "
            f"and still misses {_ids(dropped)}."
        )
    if differs := missed & assembly.recovered:
        sentences.append(
            f"The site misses {_ids(differs)} in the assembled strategy, "
            "although the measured criteria recover it."
        )
    return sentences


def _admitted_sentences(assembly: Assembly, negative: NegativeControls) -> list[str]:
    admitted = frozenset(negative.admitted_ids)
    sentences: list[str] = []
    if predicted := admitted & assembly.admitted:
        sentences.append(
            f"The strategy holds the limit of {MAX_CRITERIA} criteria "
            f"and still admits {_ids(predicted)}."
            if assembly.capped
            else f"No measured criterion excludes {_ids(predicted)} "
            "without losing a recovered positive."
        )
    if differs := admitted - assembly.admitted:
        sentences.append(
            f"The site returns {_ids(differs)} in the assembled strategy, "
            "although the measured criteria exclude it."
        )
    return sentences


def _no_tree(measured: list[MeasuredCandidate]) -> str:
    if _held(measured):
        return "No measured criterion tells the positives from the negatives."
    return "No measured criterion recovers any positive."


def shortfall(
    mode: SeparationMode,
    assembly: Assembly,
    positive: PositiveControls | None,
    negative: NegativeControls | None,
    measured: list[MeasuredCandidate],
) -> list[str]:
    """One sentence per gap of the read, built from ids. Empty when nothing is missing.

    ``positive`` and ``negative`` are the confirm read of the assembled tree.
    """
    if assembly.tree is None or positive is None or negative is None:
        return [_no_tree(measured)]
    sentences = _missed_sentences(assembly, positive, measured)
    if mode == "exact":
        sentences.extend(_admitted_sentences(assembly, negative))
    elif informs(positive, negative) != "recovering":
        sentences.append(
            "The assembled strategy does not tell the positives from the negatives."
        )
    return sentences
