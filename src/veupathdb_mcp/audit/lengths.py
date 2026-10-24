"""Protein lengths across an ortholog group: whether a member is an outlier and which
member it is read against."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from veupathdb_mcp.audit.genes import GeneRow, GroupMember, is_coding
from veupathdb_mcp.catalog.group_ids import is_group_id, is_residual

type LengthClass = Literal["SHORT", "LONG", "TYPICAL", "SPLIT", "UNQUALIFIED"]
type RelativeTier = Literal["SAME_GENUS", "OTHER_GENERA"]

MIN_ORGANISMS = 8
MAX_SPREAD = 0.3
SHORT_BELOW = 0.7
LONG_ABOVE = 1.5
SPLIT_PART_BELOW = 0.85
SPLIT_SUM = (0.8, 1.35)
MIN_RELATIVES = 2
MIN_MEDIAN = 80
RELATIVE_SHORT_SHARE = 0.85
RELATIVE_LONG_SHARE = 1.15


def species_of(organism: str) -> str:
    return " ".join(organism.split()[:2])


def genus_of(organism: str) -> str:
    return organism.split(maxsplit=1)[0]


def is_orthology_group(group: str) -> bool:
    return is_group_id(group) and not is_residual(group)


def _coding_length(row: GeneRow) -> int | None:
    return row.protein_length if is_coding(row) and row.protein_length else None


type Group = Sequence[GroupMember]
type Members = dict[str, dict[str, int]]


def _members(parts: Sequence[GeneRow], group: Group) -> Members:
    members: Members = defaultdict(dict)
    for member in group:
        if member.protein_length:
            members[member.organism][member.gene] = member.protein_length
    listed = {member.gene for member in group}
    for index, part in enumerate(parts):
        if index and part.gene not in listed:
            continue
        members[part.organism].pop(part.gene, None)
        if length := _coding_length(part):
            members[part.organism][part.gene] = length
    return {organism: genes for organism, genes in members.items() if genes}


def _longest(members: Members) -> dict[str, int]:
    return {organism: max(n.values()) for organism, n in members.items()}


class GroupProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    organisms: int
    median: float
    spread: float
    copies: float

    @property
    def qualifies(self) -> bool:
        return (
            self.organisms >= MIN_ORGANISMS
            and self.median >= MIN_MEDIAN
            and self.spread <= MAX_SPREAD
            and self.copies == 1
        )

    @classmethod
    def of(cls, parts: Sequence[GeneRow], group: Group) -> GroupProfile:
        return cls.of_members(_members(parts, group))

    @classmethod
    def of_members(cls, members: Members) -> GroupProfile:
        tops = [max(n.values()) for n in members.values()]
        if not tops:
            return cls(organisms=0, median=0.0, spread=0.0, copies=0.0)
        median = statistics.median(tops)
        quartiles = statistics.quantiles(tops, n=4) if len(tops) > 1 else [median] * 3
        return cls(
            organisms=len(tops),
            median=median,
            spread=(quartiles[2] - quartiles[0]) / median,
            copies=statistics.median(len(n) for n in members.values()),
        )


class _Expectation(BaseModel):
    model_config = ConfigDict(frozen=True)

    median: float
    relatives: list[int]


class NotChecked(BaseModel):
    model_config = ConfigDict(frozen=True)

    length_class: Literal["TYPICAL", "LONG", "UNQUALIFIED"]
    ratio: float | None
    expected: float
    profile: GroupProfile
    reference: GroupMember | None


class Confirmable(BaseModel):
    model_config = ConfigDict(frozen=True)

    length_class: Literal["SHORT", "SPLIT"]
    ratio: float
    expected: float
    profile: GroupProfile
    reference: GroupMember
    reference_length: int
    lengths: list[int]


def _expectation(gene: GeneRow, members: Members) -> _Expectation:
    genus = genus_of(gene.organism)
    kin = [
        n
        for organism, n in _longest(members).items()
        if organism != gene.organism and genus_of(organism) == genus
    ]
    if len(kin) >= MIN_RELATIVES:
        return _Expectation(median=statistics.median(kin), relatives=kin)
    return _Expectation(median=GroupProfile.of_members(members).median, relatives=[])


def _lengths(parts: list[GeneRow]) -> list[int] | None:
    lengths = [n for part in parts if (n := _coding_length(part))]
    return lengths if len(lengths) == len(parts) else None


def _placed(parts: list[GeneRow], members: Members) -> bool:
    own = members.get(parts[0].organism, {})
    return sorted(own) == sorted(part.gene for part in parts)


def _single_class(length: int, expected: _Expectation) -> LengthClass:
    ratio = length / expected.median
    low = RELATIVE_SHORT_SHARE * expected.median
    high = RELATIVE_LONG_SHARE * expected.median
    if ratio < SHORT_BELOW:
        agreed = all(n >= low for n in expected.relatives)
        return "SHORT" if agreed else "UNQUALIFIED"
    if ratio > LONG_ABOVE:
        agreed = all(n <= high for n in expected.relatives)
        return "LONG" if agreed else "UNQUALIFIED"
    return "TYPICAL"


def _split_class(lengths: list[int], expected: _Expectation) -> LengthClass:
    low, high = SPLIT_SUM
    each_short = max(lengths) < SPLIT_PART_BELOW * expected.median
    if each_short and low <= sum(lengths) / expected.median <= high:
        return "SPLIT"
    return "TYPICAL"


def _judgeable(parts: list[GeneRow], members: Members) -> bool:
    return (
        GroupProfile.of_members(members).qualifies
        and is_orthology_group(parts[0].ortholog_group)
        and _placed(parts, members)
    )


def call_length(parts: list[GeneRow], group: Group) -> Confirmable | NotChecked:
    if len(parts) not in {1, 2}:
        msg = f"a length call reads one gene or a pair, not {len(parts)}"
        raise ValueError(msg)
    members = _members(parts, group)
    expected = _expectation(parts[0], members)
    reference = closest_reference(parts[0], group)
    lengths = _lengths(parts)
    unchecked = NotChecked(
        length_class="UNQUALIFIED",
        ratio=round(sum(lengths) / expected.median, 3)
        if lengths and expected.median
        else None,
        expected=expected.median,
        profile=GroupProfile.of_members(members),
        reference=reference,
    )
    if lengths is None or reference is None or not _judgeable(parts, members):
        return unchecked
    match (
        _single_class(lengths[0], expected)
        if len(lengths) == 1
        else _split_class(lengths, expected)
    ):
        case "SHORT" | "SPLIT" as confirmable:
            return Confirmable(
                length_class=confirmable,
                ratio=round(sum(lengths) / expected.median, 3),
                expected=expected.median,
                profile=unchecked.profile,
                reference=reference,
                reference_length=_longest(members)[reference.organism],
                lengths=lengths,
            )
        case "TYPICAL" | "LONG" | "UNQUALIFIED" as other:
            return NotChecked(
                length_class=other,
                ratio=unchecked.ratio,
                expected=expected.median,
                profile=unchecked.profile,
                reference=reference,
            )


def classify(gene: GeneRow, group: Group) -> LengthClass:
    return call_length([gene], group).length_class


def closest_reference(gene: GeneRow, group: Group) -> GroupMember | None:
    members = _members([gene], group)
    expected = _expectation(gene, members).median
    single = {
        member
        for organism, genes in members.items()
        if organism != gene.organism and len(genes) == 1
        for member in genes
    }
    return min(
        (row for row in group if row.gene in single),
        key=lambda row: (
            species_of(row.organism) != species_of(gene.organism),
            genus_of(row.organism) != genus_of(gene.organism),
            abs((row.protein_length or 0) - expected),
            row.gene,
        ),
        default=None,
    )


class Relatives(BaseModel):
    model_config = ConfigDict(frozen=True)

    tier: RelativeTier
    lengths: dict[str, int]

    @property
    def median(self) -> float:
        return statistics.median(self.lengths.values())


def relatives_of(reference: GeneRow, model: GeneRow, group: Group) -> Relatives | None:
    left_out = {reference.organism, model.organism}
    tops = {
        organism: n
        for organism, n in _longest(_members([], group)).items()
        if organism not in left_out
    }
    genus = genus_of(reference.organism)
    species = species_of(reference.organism)
    tiers: dict[RelativeTier, dict[str, int]] = {
        "SAME_GENUS": {
            organism: n
            for organism, n in tops.items()
            if genus_of(organism) == genus and species_of(organism) != species
        },
        "OTHER_GENERA": {
            organism: n for organism, n in tops.items() if genus_of(organism) != genus
        },
    }
    for tier, lengths in tiers.items():
        if len(lengths) >= MIN_RELATIVES:
            return Relatives(tier=tier, lengths=lengths)
    return None


def relatives_median(reference: GeneRow, model: GeneRow, group: Group) -> float | None:
    found = relatives_of(reference, model, group)
    return None if found is None else found.median
