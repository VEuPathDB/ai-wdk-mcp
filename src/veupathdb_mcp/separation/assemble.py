"""The boolean the measured sets assemble by direction, and the gaps it leaves.

A recovering candidate covers and intersects, an excluding one is subtracted
alone or as a branch that keeps the positives it holds, and one that informs
neither way never enters a tree. Set algebra on the
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
    SeparationOperator,
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


def _combined(
    operator: SeparationOperator, left: frozenset[str], right: frozenset[str]
) -> frozenset[str]:
    if operator == CombineOp.UNION:
        return left | right
    if operator == CombineOp.INTERSECT:
        return left & right
    return left - right


@dataclass(frozen=True)
class _Part:
    node: SeparationNode
    recovered: frozenset[str]
    admitted: frozenset[str]
    used: tuple[str, ...]
    size: int

    @classmethod
    def leaf(cls, m: MeasuredCandidate) -> "_Part":
        return cls(
            node=SeparationNode(kind="leaf", candidate_id=m.candidate.id),
            recovered=_recovered(m),
            admitted=_admitted(m),
            used=(m.candidate.id,),
            size=m.result_size,
        )

    @classmethod
    def branch(
        cls,
        operator: SeparationOperator,
        left: MeasuredCandidate,
        right: MeasuredCandidate,
    ) -> "_Part":
        first, second = cls.leaf(left), cls.leaf(right)
        return cls(
            node=SeparationNode(
                kind="combine", operator=operator, inputs=[first.node, second.node]
            ),
            recovered=_combined(operator, first.recovered, second.recovered),
            admitted=_combined(operator, first.admitted, second.admitted),
            used=(*first.used, *second.used),
            size=left.result_size,
        )


@dataclass
class _Tree:
    node: SeparationNode
    recovered: frozenset[str]
    admitted: frozenset[str]
    used: list[str] = field(default_factory=list)

    @classmethod
    def start(cls, m: MeasuredCandidate) -> "_Tree":
        part = _Part.leaf(m)
        return cls(
            node=part.node,
            recovered=part.recovered,
            admitted=part.admitted,
            used=list(part.used),
        )

    def add(self, operator: SeparationOperator, part: _Part) -> None:
        self.node = SeparationNode(
            kind="combine", operator=operator, inputs=[self.node, part.node]
        )
        self.used.extend(part.used)
        self.recovered = _combined(operator, self.recovered, part.recovered)
        self.admitted = _combined(operator, self.admitted, part.admitted)

    def full(self) -> bool:
        return len(self.used) >= MAX_CRITERIA

    def fits(self, part: _Part) -> bool:
        return len(self.used) + len(part.used) <= MAX_CRITERIA

    def unused(self, m: MeasuredCandidate) -> bool:
        return m.candidate.id not in self.used


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
            tree.add(CombineOp.UNION, _Part.leaf(best))
        covered = tree.recovered
    return tree, False


def _branches(
    tree: _Tree,
    recovering: list[MeasuredCandidate],
    excluding: list[MeasuredCandidate],
) -> list[_Part]:
    """Each excluding candidate less another candidate, and each two excluding
    candidates intersected."""
    noisy = [m for m in excluding if tree.unused(m)]
    others = [m for m in (*recovering, *excluding) if tree.unused(m)]
    branches = [
        _Part.branch(CombineOp.MINUS, left, right)
        for left in noisy
        for right in others
        if right is not left
    ]
    branches.extend(
        _Part.branch(CombineOp.INTERSECT, left, right)
        for index, left in enumerate(noisy)
        for right in noisy[index + 1 :]
    )
    return [branch for branch in branches if tree.fits(branch)]


def _best_move(
    tree: _Tree,
    recovering: list[MeasuredCandidate],
    excluding: list[MeasuredCandidate],
) -> tuple[SeparationOperator, _Part, int] | None:
    """The move that removes the most negatives and keeps every recovered positive.

    A tie goes to one candidate over a branch of two, then to an intersection,
    then to the smaller result.
    """
    offered: list[tuple[SeparationOperator, _Part]] = [
        (CombineOp.INTERSECT, _Part.leaf(m)) for m in recovering if tree.unused(m)
    ]
    offered.extend(
        (CombineOp.MINUS, _Part.leaf(m)) for m in excluding if tree.unused(m)
    )
    offered.extend(
        (CombineOp.MINUS, branch) for branch in _branches(tree, recovering, excluding)
    )
    moves: list[tuple[SeparationOperator, _Part, int]] = [
        (
            operator,
            part,
            len(tree.admitted - _combined(operator, tree.admitted, part.admitted)),
        )
        for operator, part in offered
        if _combined(operator, tree.recovered, part.recovered) == tree.recovered
    ]
    return max(
        moves,
        key=lambda move: (
            move[2],
            len(move[1].used) == 1,
            move[0] == CombineOp.INTERSECT,
            -move[1].size,
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
    excluding ones, alone or in a branch that keeps the positives they hold.
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
