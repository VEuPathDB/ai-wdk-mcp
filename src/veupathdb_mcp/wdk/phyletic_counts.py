from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator
from veupathdb.domain.parameters import PhyleticTree
from veupathdb.errors import ValidationError
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.group_counts import GroupCountReports, site_taxonomy
from veupathdb_mcp.catalog.phyletic_builder import (
    PhyleticExpressionResult,
    expression_of,
    least_expression_too_large,
    probe_pattern,
)
from veupathdb_mcp.catalog.phyletic_compare import (
    SideCounts,
    compare_counts,
    require_absent_excluded,
    summed,
)
from veupathdb_mcp.catalog.phyletic_logic import (
    CALL_SECONDS,
    PhyleticExpressionTooLargeError,
    PhyleticExpressionTooSlowError,
    admit_expression,
    clock,
    cover,
)
from veupathdb_mcp.catalog.phyletic_pattern import CompareTerm, PhyleticPattern
from veupathdb_mcp.wdk.group_clouds import MAX_CLOUD_WORDS, read_group_proteins

MAX_COMPARISON_REQUESTS = 24
REQUESTS_PER_SLICE = 2
REQUESTS_PER_GENOME = 1 + REQUESTS_PER_SLICE
_LISTED = 4

type Side = Literal["left", "right"]
type Slice = tuple[str, ...]


def _named(slices: Sequence[Slice]) -> str:
    shown = [
        "+".join(part[:_LISTED]) + (" ..." if len(part) > _LISTED else "")
        for part in slices
    ]
    return "; ".join(shown)


class ComparisonRequestsError(ValidationError):
    def __init__(self, needed: int, narrower: Sequence[Slice]) -> None:
        self.needed = needed
        self.narrower = tuple(narrower)
        super().__init__(
            title="The comparison needs more requests than one call sends",
            detail=(
                f"Computing the comparison from per-group protein counts needs at "
                f"least {needed} requests, past the {MAX_COMPARISON_REQUESTS} one call "
                f"sends. Compare narrower sets, one at a time: {_named(self.narrower)}."
            ),
        )


class PerGenomeNeedsTaskError(ValidationError):
    def __init__(self, genomes: int, needed: int) -> None:
        self.genomes = genomes
        self.needed = needed
        super().__init__(
            title="A per_genome comparison this wide needs a background task",
            detail=(
                f"A per_genome comparison past one expression reads each of its "
                f"{genomes} genomes on its own, {needed} requests, past the "
                f"{MAX_COMPARISON_REQUESTS} one call sends. It needs a background "
                "task, or compare averages or totals instead."
            ),
        )


class GenomePastCloudCapError(ValidationError):
    def __init__(self, genome: str, groups: int) -> None:
        self.genome = genome
        self.groups = groups
        super().__init__(
            title="One genome holds more groups than a group cloud counts",
            detail=(
                f"Genome {genome} alone holds {groups} groups, past the group word "
                f"cloud's cap of {MAX_CLOUD_WORDS}, and one genome cannot be split, so "
                "this compare cannot be computed from per-group protein counts."
            ),
        )


class ComparisonOutOfTimeError(ValidationError):
    def __init__(self, sent: int) -> None:
        self.sent = sent
        super().__init__(
            title="The comparison ran past the call budget",
            detail=(
                f"Computing the comparison from per-group protein counts passed the "
                f"{CALL_SECONDS} s call budget after {sent} requests. Compare narrower "
                "sets."
            ),
        )


class NestedCompareTooLargeError(ValidationError):
    def __init__(self, past: ValidationError) -> None:
        super().__init__(
            title=past.title,
            detail=(
                f"{past.detail} Only a compare that is the whole pattern is computed "
                "from per-group protein counts; this compare sits inside all_of, "
                "any_of or none_of, so the pattern is refused. Ask the compare on its "
                "own, or narrow its sets."
            ),
        )


class SpeciesGenomes(CamelModel):
    model_config = ConfigDict(frozen=True)

    species: str
    genomes: int = Field(ge=1)


class ComputedSet(CamelModel):
    model_config = ConfigDict(frozen=True)

    side: Side
    genomes: int = Field(ge=1)
    species: tuple[SpeciesGenomes, ...]
    groups: int = Field(ge=0)
    proteins: int = Field(ge=0)


class ComputedComparisonResult(CamelModel):
    model_config = ConfigDict(frozen=True)

    route: Literal["computed"] = "computed"
    site_id: str
    reading: str
    groups: int = Field(ge=0)
    group_ids: tuple[str, ...]
    both_held: int = Field(ge=0)
    left_only: int = Field(ge=0)
    right_only: int = Field(ge=0)
    ties: int = Field(ge=0)
    residual_groups: int = Field(ge=0)
    sets: tuple[ComputedSet, ComputedSet]
    probe_requests: int = Field(ge=0)
    compute_requests: int = Field(ge=0)

    @model_validator(mode="after")
    def _counted_ids(self) -> Self:
        parts = self.both_held + self.left_only + self.right_only
        if not self.groups == len(self.group_ids) == parts:
            msg = (
                f"groups is {self.groups} for {len(self.group_ids)} group ids and "
                f"{parts} groups by set"
            )
            raise ValueError(msg)
        return self


type PhyleticPatternResult = Annotated[
    PhyleticExpressionResult | ComputedComparisonResult, Field(discriminator="route")
]


class _Requests:
    def __init__(self, started: float) -> None:
        self.sent = 0
        self.deadline = started + CALL_SECONDS

    def remaining(self) -> float:
        return self.deadline - clock()

    def spend(self, narrower: Sequence[Slice], requests: int = 1) -> None:
        if self.remaining() <= 0:
            raise ComparisonOutOfTimeError(self.sent)
        if self.sent + requests > MAX_COMPARISON_REQUESTS:
            raise ComparisonRequestsError(self.sent + requests, narrower)
        self.sent += requests


def _ordered(tree: PhyleticTree, genomes: frozenset[str]) -> Slice:
    return tuple(dict.fromkeys(n.code for n in tree.nodes() if n.code in genomes))


def _halves(genomes: Slice) -> tuple[Slice, Slice]:
    middle = len(genomes) // 2
    return genomes[:middle], genomes[middle:]


async def _lone(
    genome: str, requests: _Requests, counts: GroupCountReports
) -> list[Slice]:
    requests.spend([(genome,)])
    groups = await counts.groups(f"{genome}>=1T")
    if groups > MAX_CLOUD_WORDS:
        raise GenomePastCloudCapError(genome, groups)
    return [(genome,)]


async def _slices(
    tree: PhyleticTree, genomes: Slice, requests: _Requests, counts: GroupCountReports
) -> list[Slice]:
    if len(genomes) == 1:
        return await _lone(genomes[0], requests, counts)
    first, second = _halves(genomes)
    expression = f"{cover(tree, frozenset(genomes))}>=1T"
    admit_expression(expression)
    requests.spend([first, second])
    if await counts.groups(expression) <= MAX_CLOUD_WORDS:
        return [genomes]
    return [
        *await _slices(tree, first, requests, counts),
        *await _slices(tree, second, requests, counts),
    ]


async def _plan(
    site_id: str, tree: PhyleticTree, sides: Sequence[Slice], requests: _Requests
) -> list[list[Slice]]:
    counts = GroupCountReports(site_id, MAX_COMPARISON_REQUESTS)
    planned = [await _slices(tree, genomes, requests, counts) for genomes in sides]
    every = [part for side in planned for part in side]
    needed = requests.sent + REQUESTS_PER_SLICE * len(every)
    if needed > MAX_COMPARISON_REQUESTS:
        raise ComparisonRequestsError(needed, every)
    return planned


def _require_per_genome_plan(genomes: int) -> None:
    needed = REQUESTS_PER_GENOME * genomes
    if needed > MAX_COMPARISON_REQUESTS:
        raise PerGenomeNeedsTaskError(genomes, needed)


async def _per_genome_plan(
    site_id: str, sides: Sequence[Slice], requests: _Requests
) -> list[list[Slice]]:
    _require_per_genome_plan(sum(len(side) for side in sides))
    counts = GroupCountReports(site_id, MAX_COMPARISON_REQUESTS)
    return [
        [part for genome in side for part in await _lone(genome, requests, counts)]
        for side in sides
    ]


async def _read(
    site_id: str, planned: Sequence[Slice], requests: _Requests
) -> list[Counter[str]]:
    read: list[Counter[str]] = []
    for part in planned:
        requests.spend(planned, REQUESTS_PER_SLICE)
        proteins = await read_group_proteins(
            site_id, part, budget_seconds=requests.remaining()
        )
        read.append(proteins.counts())
    return read


def _species(tree: PhyleticTree, genomes: Slice) -> tuple[SpeciesGenomes, ...]:
    held = [
        SpeciesGenomes(species=group.species, genomes=len(set(group.genomes)))
        for group in tree.species_groups(list(genomes))
    ]
    return tuple(sorted(held, key=lambda one: (-one.genomes, one.species)))


def _computed_set(
    tree: PhyleticTree, side: Side, genomes: Slice, counts: SideCounts
) -> ComputedSet:
    return ComputedSet(
        side=side,
        genomes=len(genomes),
        species=_species(tree, genomes),
        groups=len(counts.totals),
        proteins=counts.totals.total(),
    )


async def compute_comparison(
    site_id: str,
    term: CompareTerm,
    *,
    probe_requests: int = 0,
    started: float | None = None,
) -> ComputedComparisonResult:
    factor = Fraction(str(term.factor))
    require_absent_excluded(term.condition, factor)
    tree = await site_taxonomy(site_id)
    left = _ordered(tree, term.left.genomes(tree))
    right = _ordered(tree, term.right.genomes(tree))
    requests = _Requests(clock() if started is None else started)
    per_genome = term.reading == "per_genome"
    planned = (
        await _per_genome_plan(site_id, [left, right], requests)
        if per_genome
        else await _plan(site_id, tree, [left, right], requests)
    )
    sides: list[SideCounts] = []
    for genomes, parts in zip((left, right), planned, strict=True):
        read = await _read(site_id, parts, requests)
        sides.append(
            SideCounts(
                genomes=len(genomes),
                totals=summed(read),
                per_genome=tuple(read) if per_genome else (),
            )
        )
    compared = compare_counts(sides[0], sides[1], term.reading, term.condition, factor)
    return ComputedComparisonResult(
        site_id=site_id,
        reading=(
            f"{term.outline()}; computed from each group's protein counts, the "
            "groups the expression would select"
        ),
        groups=len(compared.groups),
        group_ids=compared.groups,
        both_held=len(compared.both),
        left_only=len(compared.left_only),
        right_only=len(compared.right_only),
        ties=compared.ties,
        residual_groups=compared.residual,
        sets=(
            _computed_set(tree, "left", left, sides[0]),
            _computed_set(tree, "right", right, sides[1]),
        ),
        probe_requests=probe_requests,
        compute_requests=requests.sent,
    )


async def answer_phyletic_pattern(
    site_id: str, pattern: PhyleticPattern
) -> PhyleticExpressionResult | ComputedComparisonResult:
    started = clock()
    match pattern:
        case CompareTerm():
            if await least_expression_too_large(site_id, pattern):
                return await compute_comparison(site_id, pattern, started=started)
    found = await probe_pattern(site_id, pattern)
    try:
        return await expression_of(site_id, pattern, found)
    except (PhyleticExpressionTooLargeError, PhyleticExpressionTooSlowError) as past:
        match pattern:
            case CompareTerm():
                return await compute_comparison(
                    site_id, pattern, probe_requests=found.reads, started=started
                )
        if found.probes and not await least_expression_too_large(site_id, pattern):
            raise NestedCompareTooLargeError(past) from past
        raise
