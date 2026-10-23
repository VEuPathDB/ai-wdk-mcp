from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from heapq import merge
from itertools import accumulate, product
from math import ceil, floor, prod
from time import monotonic
from typing import Literal, NoReturn

from veupathdb.domain.parameters import PhyleticNode, PhyleticTree
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog.site_cost import SiteCost

Condition = Literal["at_least", "at_most", "exactly", "more_than", "fewer_than"]
Join = Literal["AND", "OR"]

CALL_SECONDS = 300
AND_WIDTH = len(" AND ")
OR_WIDTH = len(" OR ")
MEASURED_SECONDS_PER_ATOM = 2.83e-6
HOST_MARGIN = 2
SECONDS_PER_ATOM = MEASURED_SECONDS_PER_ATOM * HOST_MARGIN
MEASURED_SECONDS_PER_COVER = 19.14e-3
SECONDS_PER_COVER = MEASURED_SECONDS_PER_COVER * HOST_MARGIN

type Span = tuple[int, int | None]
type Key = tuple[frozenset[str], bool]


def refuse(detail: str) -> NoReturn:
    raise ValidationError(
        title="The phyletic pattern cannot be written as a phyletic_expression",
        detail=detail,
    )


@dataclass(frozen=True, slots=True)
class Atom:
    genomes: frozenset[str]
    taxa: bool
    lo: int
    hi: int | None

    @property
    def top(self) -> int | None:
        return len(self.genomes) if self.taxa else None

    def meet(self, other: Atom) -> Atom | None:
        lo = max(self.lo, other.lo)
        highs = [high for high in (self.hi, other.hi) if high is not None]
        hi = min(highs) if highs else None
        if hi is not None and hi < lo:
            return None
        return Atom(self.genomes, self.taxa, lo, hi)

    def negated(self) -> Dnf:
        clauses: list[Clause] = []
        if self.lo > 0:
            clauses.append((Atom(self.genomes, self.taxa, 0, self.lo - 1),))
        if self.hi is not None and (self.top is None or self.hi < self.top):
            clauses.append((Atom(self.genomes, self.taxa, self.hi + 1, self.top),))
        return tuple(clauses)

    def options(self, unit: str) -> list[tuple[str, ...]]:
        mark = "T" if self.taxa else ""
        found: list[tuple[str, ...]] = []
        if self.lo == 0:
            found.append((f"{unit}=0{mark}",))
        low = max(self.lo, 1)
        if self.hi is None or self.hi == self.top:
            found.append((f"{unit}>={low}{mark}",))
        elif self.hi == low:
            found.append((f"{unit}={low}{mark}",))
        elif self.hi > low and low == 1:
            found.append((f"{unit}<={self.hi}{mark}",))
        elif self.hi > low:
            found.append((f"{unit}>={low}{mark}", f"{unit}<={self.hi}{mark}"))
        return found


type Clause = tuple[Atom, ...]
type Dnf = tuple[Clause, ...]

TRUE: Dnf = ((),)
FALSE: Dnf = ()


def bounds(condition: Condition | Literal["absent"], x: Fraction) -> Span | None:
    match condition:
        case "absent":
            return 0, 0
        case "at_least":
            return ceil(x), None
        case "more_than":
            return floor(x) + 1, None
        case "at_most":
            return 0, floor(x)
        case "fewer_than":
            return None if ceil(x) < 1 else (0, ceil(x) - 1)
        case "exactly":
            return (int(x), int(x)) if x.denominator == 1 else None


def atom(genomes: frozenset[str], span: Span | None, *, taxa: bool) -> Dnf:
    if span is None:
        return FALSE
    lo, hi = span
    top = len(genomes) if taxa else None
    if top is not None:
        hi = top if hi is None else min(hi, top)
    if hi is not None and hi < lo:
        return FALSE
    if lo == 0 and hi == top:
        return TRUE
    return ((Atom(genomes, taxa, lo, hi),),)


def _clause(atoms: Iterable[Atom]) -> Clause | None:
    held: dict[tuple[frozenset[str], bool], Atom] = {}
    for one in atoms:
        key = (one.genomes, one.taxa)
        prior = held.get(key)
        merged = one if prior is None else prior.meet(one)
        if merged is None:
            return None
        held[key] = merged
    empty = {one.genomes for one in held.values() if one.hi == 0}
    if any(one.lo > 0 and one.genomes in empty for one in held.values()):
        return None
    kept: list[Atom] = []
    written: set[frozenset[str]] = set()
    for one in held.values():
        if one.genomes in empty:
            if one.hi != 0 or one.genomes in written:
                continue
            written.add(one.genomes)
        kept.append(one)
    return tuple(kept)


def _unique(clauses: Iterable[Clause]) -> Dnf:
    found: dict[frozenset[Atom], Clause] = {}
    for clause in clauses:
        if not clause:
            return TRUE
        found.setdefault(frozenset(clause), clause)
    return tuple(found.values())


@dataclass(frozen=True, slots=True)
class _Index:
    key: Key | None
    every: range
    loose: tuple[int, ...]
    values: tuple[int, ...]
    buckets: tuple[tuple[int, ...], ...]
    starts: tuple[int, ...]
    widths: tuple[int, ...]
    loose_width: int
    bucket_widths: tuple[int, ...]

    def _slice(self, clause: Clause) -> tuple[int, int] | None:
        found = [one for one in clause if (one.genomes, one.taxa) == self.key]
        if not found:
            return None
        lo, hi = found[0].lo, found[0].hi
        last = len(self.values) if hi is None else bisect_right(self.values, hi)
        return bisect_left(self.values, lo), last

    def count(self, clause: Clause) -> int:
        bounds = self._slice(clause)
        if bounds is None:
            return len(self.every)
        first, last = bounds
        return len(self.loose) + self.starts[last] - self.starts[first]

    def atoms(self, clause: Clause) -> int:
        bounds = self._slice(clause)
        if bounds is None:
            matched = self.widths[-1]
        else:
            first, last = bounds
            matched = (
                self.loose_width + self.bucket_widths[last] - self.bucket_widths[first]
            )
        return len(clause) * self.count(clause) + matched

    def matches(self, clause: Clause) -> Iterator[int]:
        bounds = self._slice(clause)
        if bounds is None:
            return iter(self.every)
        first, last = bounds
        return merge(self.loose, *self.buckets[first:last])


def _index(added: Dnf) -> _Index:
    exact: dict[Key, dict[int, list[int]]] = {}
    for position, clause in enumerate(added):
        for one in clause:
            if one.lo == one.hi:
                exact.setdefault((one.genomes, one.taxa), {}).setdefault(
                    one.lo, []
                ).append(position)
    every = range(len(added))
    widths = (0, *accumulate(len(clause) for clause in added))
    if not exact:
        return _Index(None, every, (), (), (), (0,), widths, 0, (0,))
    key = max(exact, key=lambda held: sum(map(len, exact[held].values())))
    by_value = exact[key]
    values = tuple(sorted(by_value))
    buckets = tuple(tuple(by_value[value]) for value in values)
    keyed = {position for bucket in buckets for position in bucket}
    loose = tuple(position for position in every if position not in keyed)
    return _Index(
        key,
        every,
        loose,
        values,
        buckets,
        (0, *accumulate(len(bucket) for bucket in buckets)),
        widths,
        sum(len(added[position]) for position in loose),
        (
            0,
            *accumulate(
                sum(len(added[position]) for position in bucket) for bucket in buckets
            ),
        ),
    )


def _product(held: Dnf, added: Dnf, guard: Guard) -> Dnf:
    index = _index(added)
    guard.charge(sum(index.atoms(left) for left in held))
    merged: dict[frozenset[Atom], Clause] = {}
    characters = 0
    for left in held:
        for position in index.matches(left):
            clause = _clause((*left, *added[position]))
            if clause is None:
                continue
            if not clause:
                return TRUE
            key = frozenset(clause)
            if key in merged:
                continue
            merged[key] = clause
            characters += guard.width(clause) + OR_WIDTH
            guard.admit(characters, len(merged), atoms=len(clause), partial=True)
    return tuple(merged.values())


def both(parts: Iterable[Dnf], guard: Guard) -> Dnf:
    result = TRUE
    for part in parts:
        result = _product(result, part, guard)
    return result


def either(parts: Iterable[Dnf], guard: Guard) -> Dnf:
    merged: dict[frozenset[Atom], Clause] = {}
    characters = -OR_WIDTH
    for part in parts:
        for clause in part:
            if not clause:
                return TRUE
            key = frozenset(clause)
            if key in merged:
                continue
            merged[key] = clause
            characters += guard.width(clause) + OR_WIDTH
            guard.admit(characters, len(merged), atoms=len(clause), partial=True)
    return tuple(merged.values())


def neither(dnf: Dnf, guard: Guard) -> Dnf:
    return both(
        (
            _unique(negated for one in clause for negated in one.negated())
            for clause in dnf
        ),
        guard,
    )


def _covering(
    tree: PhyleticTree, nodes: Sequence[PhyleticNode], wanted: frozenset[str]
) -> list[str]:
    codes: list[str] = []
    for node in nodes:
        held = tree.genomes_under([node.code])
        if held and held <= wanted:
            codes.append(node.code)
        elif held & wanted:
            codes.extend(_covering(tree, node.children, wanted))
    return codes


def cover(tree: PhyleticTree, genomes: frozenset[str]) -> str:
    return "+".join(_covering(tree, tree.roots, genomes))


@dataclass(frozen=True, slots=True)
class Probe:
    units: tuple[str, ...]
    join: Join

    def at(self, count: int) -> str:
        return f" {self.join} ".join(f"{unit}>={count}" for unit in self.units)


_NARROW_BUILD = (
    "Narrow the pattern: fewer terms under all_of, or compares over sides with "
    "smaller counts."
)


def _written_width(option: tuple[str, ...]) -> int:
    return sum(len(unit) for unit in option) + AND_WIDTH * len(option)


def clock() -> float:
    return monotonic()


class Guard:
    def __init__(
        self,
        tree: PhyleticTree,
        cost: SiteCost,
        probes: int,
        *,
        start: float | None = None,
    ) -> None:
        self.tree = tree
        self.cost = cost
        self.probes = probes
        self.atoms = 0
        self.covers = 0
        self.start = monotonic() if start is None else start
        self.deadline = self.start + CALL_SECONDS - cost.fixed
        self._units: dict[frozenset[str], str] = {}

    def after(self, probes: int) -> Guard:
        guard = Guard(self.tree, self.cost, probes, start=self.start)
        guard.atoms = self.atoms
        guard.covers = self.covers
        guard._units.update(self._units)
        return guard

    @property
    def building(self) -> float:
        return self.atoms * SECONDS_PER_ATOM + self.covers * SECONDS_PER_COVER

    @property
    def characters(self) -> int:
        building = self.building
        return min(
            self.cost.longest,
            self.cost.characters_within(CALL_SECONDS - building, self.probes),
        )

    def seconds(self, characters: int) -> float:
        return self.cost.seconds(characters, self.probes) + self.building

    def charge(self, atoms: int) -> None:
        self._add(atoms)
        self._on_time(0)

    def _add(self, atoms: int) -> None:
        self.atoms += atoms
        if self.seconds(0) > CALL_SECONDS:
            refuse(
                f"Multiplied out, the pattern tries at least {self.atoms} clause "
                f"atoms, about {self.atoms * SECONDS_PER_ATOM:.0f} s of building at "
                f"{SECONDS_PER_ATOM * 1e9:.0f} ns an atom, so with its reads and its "
                f"count it passes the {CALL_SECONDS} s call budget. {_NARROW_BUILD}"
            )

    def _charge_cover(self) -> None:
        self.covers += 1
        if self.seconds(0) > CALL_SECONDS:
            refuse(
                f"The pattern names at least {self.covers} distinct genome sets, and "
                f"reading their covers takes about "
                f"{self.covers * SECONDS_PER_COVER:.0f} s at "
                f"{SECONDS_PER_COVER * 1e3:.0f} ms a set, so with its building, its "
                f"reads and its count it passes the {CALL_SECONDS} s call budget. "
                "Narrow the pattern: fewer genomes under each_genome_of, fewer "
                "species under each_species_of, or fewer per_genome compares."
            )
        self._on_time(0)

    def _on_time(self, characters: int) -> None:
        now = monotonic()
        counting = self.cost.per_character * characters
        if now + counting <= self.deadline:
            return
        refuse(
            f"The pattern's call ran {now - self.start:.0f} s, past the "
            f"{self.deadline - self.start - counting:.0f} s the {CALL_SECONDS} s call "
            f"budget leaves it before its count. {_NARROW_BUILD}"
        )

    def unit(self, genomes: frozenset[str]) -> str:
        if genomes not in self._units:
            self._charge_cover()
            self._units[genomes] = cover(self.tree, genomes)
        return self._units[genomes]

    def options(self, one: Atom) -> list[tuple[str, ...]]:
        return one.options(self.unit(one.genomes))

    def width(self, clause: Clause) -> int:
        widths = [
            min(_written_width(option) for option in self.options(one))
            for one in clause
        ]
        return max(sum(widths) - AND_WIDTH, 0)

    def admit(
        self, characters: int, terms: int, *, atoms: int = 0, partial: bool = False
    ) -> None:
        self._add(atoms)
        if characters <= self.characters:
            self._on_time(characters)
            return
        counted = (
            f"Multiplied out, the pattern reaches at least {terms} OR terms and "
            f"{characters} characters before its last step"
            if partial
            else f"The pattern writes {terms} OR terms, {characters} characters"
        )
        if characters > self.cost.longest:
            reason = (
                f"longer than {self.cost.longest} characters, the longest expression "
                "the site was measured to answer; a longer expression needs recorded "
                "rows before it is admitted"
            )
        else:
            reason = (
                f"the site was measured to count {self.cost.per_character * 1e6:.0f} "
                f"ms per 1,000 characters plus {self.cost.fixed:.1f} s, so it needs "
                f"about {self.seconds(characters):.0f} s, past the "
                f"{CALL_SECONDS} s call budget"
            )
        refuse(
            f"{counted}: {reason}. Narrow the pattern: fewer genomes under a bound "
            "that admits absence, fewer any_of terms under all_of, or a compare over "
            "a side with smaller counts."
        )


@dataclass(frozen=True, slots=True)
class Writing:
    tree: PhyleticTree
    maxima: Mapping[Probe, int]
    guard: Guard


def _clause_characters(options: list[list[tuple[str, ...]]]) -> int:
    counts = [len(held) for held in options]
    written = sum(
        sum(_written_width(option) for option in held)
        * prod(count for other, count in enumerate(counts) if other != index)
        for index, held in enumerate(options)
    )
    return written - AND_WIDTH * prod(counts)


def _clause_units(options: list[list[tuple[str, ...]]]) -> int:
    counts = [len(held) for held in options]
    return sum(
        sum(len(option) for option in held)
        * prod(count for other, count in enumerate(counts) if other != index)
        for index, held in enumerate(options)
    )


def render(dnf: Dnf, guard: Guard) -> tuple[str, int]:
    if not dnf:
        refuse("The pattern matches no group, so it has no expression.")
    if dnf == TRUE:
        refuse("The pattern holds for every group, so it states no constraint.")
    options = [[guard.options(one) for one in clause] for clause in dnf]
    terms = sum(prod(len(held) for held in clause) for clause in options)
    guard.admit(
        sum(_clause_characters(clause) for clause in options) + OR_WIDTH * (terms - 1),
        terms,
        atoms=sum(_clause_units(clause) for clause in options),
    )
    written = dict.fromkeys(
        " AND ".join(unit for option in picked for unit in option)
        for clause in options
        for picked in product(*clause)
    )
    return " OR ".join(written), len(written)
