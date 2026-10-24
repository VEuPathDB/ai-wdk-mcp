from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog.group_ids import is_residual
from veupathdb_mcp.catalog.phyletic_logic import Condition
from veupathdb_mcp.catalog.phyletic_pattern import Reading

type Span = tuple[Fraction, Fraction]


@dataclass(frozen=True, slots=True)
class SideCounts:
    genomes: int
    totals: Counter[str]
    per_genome: tuple[Counter[str], ...] = ()

    def __post_init__(self) -> None:
        if self.per_genome and len(self.per_genome) != self.genomes:
            msg = f"{len(self.per_genome)} genome counts for {self.genomes} genomes"
            raise ValueError(msg)

    def span(self, group: str, reading: Reading) -> Span:
        match reading:
            case "averages":
                mean = Fraction(self.totals[group], self.genomes)
                return mean, mean
            case "totals":
                total = Fraction(self.totals[group])
                return total, total
            case "per_genome":
                if not self.per_genome:
                    msg = "a per_genome reading needs each genome's counts"
                    raise ValueError(msg)
                held = [counts[group] for counts in self.per_genome]
                return Fraction(min(held)), Fraction(max(held))


def holds(condition: Condition, factor: Fraction, left: Span, right: Span) -> bool:
    (low, high), (floor, ceiling) = left, right
    match condition:
        case "more_than":
            return low > factor * ceiling
        case "at_least":
            return low >= factor * ceiling
        case "fewer_than":
            return high < factor * floor
        case "at_most":
            return high <= factor * floor
        case "exactly":
            return low == high == factor * floor == factor * ceiling


_ABSENT: Span = (Fraction(0), Fraction(0))


class AbsentGroupsCompareError(ValidationError):
    def __init__(self, condition: Condition, factor: Fraction) -> None:
        self.condition = condition
        self.factor = factor
        super().__init__(
            title="The compare selects groups neither set holds",
            detail=(
                f"left {condition} {float(factor):g} times right holds at 0 proteins "
                "against 0, so its expression also selects every group neither set "
                "holds. Per-group protein counts list only the groups the two sets "
                "hold, so this compare cannot be computed from them. Compare with "
                "more_than or fewer_than, or narrow the sets until one expression "
                "states it."
            ),
        )


def require_absent_excluded(condition: Condition, factor: Fraction) -> None:
    if holds(condition, factor, _ABSENT, _ABSENT):
        raise AbsentGroupsCompareError(condition, factor)


@dataclass(frozen=True, slots=True)
class ComparedGroups:
    both: tuple[str, ...]
    left_only: tuple[str, ...]
    right_only: tuple[str, ...]
    ties: int

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(sorted((*self.both, *self.left_only, *self.right_only)))

    @property
    def residual(self) -> int:
        return sum(map(is_residual, self.groups))


def compare_counts(
    left: SideCounts,
    right: SideCounts,
    reading: Reading,
    condition: Condition,
    factor: Fraction,
) -> ComparedGroups:
    require_absent_excluded(condition, factor)
    spans = {
        group: (left.span(group, reading), right.span(group, reading))
        for group in sorted(set(left.totals) | set(right.totals))
    }
    met = {
        group
        for group, (low, high) in spans.items()
        if holds(condition, factor, low, high)
    }
    return ComparedGroups(
        both=_held(met, left.totals, right.totals, both=True),
        left_only=_held(met, left.totals, right.totals, both=False),
        right_only=_held(met, right.totals, left.totals, both=False),
        ties=sum(
            holds("exactly", Fraction(1), low, high) for low, high in spans.values()
        ),
    )


def _held(
    met: set[str], held: Counter[str], other: Counter[str], *, both: bool
) -> tuple[str, ...]:
    return tuple(sorted(group for group in met & set(held) if (group in other) == both))


def summed(slices: Sequence[Counter[str]]) -> Counter[str]:
    total: Counter[str] = Counter()
    for counts in slices:
        total.update(counts)
    return total
