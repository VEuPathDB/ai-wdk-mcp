"""A strain's protein against its species reference: the runs each side lacks, and
which side the relatives of the reference call wrong."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Literal, Self

from pydantic import ConfigDict, field_validator, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.gene_ids import GeneId, check_resolved
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.length import LengthCheck, LengthVerdict
from veupathdb_mcp.audit.lengths import GroupProfile, RelativeTier, relatives_of
from veupathdb_mcp.audit.windows import FOUND, MISSING, STEP, WINDOW, best_identity
from veupathdb_mcp.computed import computed

type SideVerdict = Literal[
    "STRAIN_SHORT", "REFERENCE_LONG", "UNCLEAR", "NO_RELATIVES", "NOT_JUDGED"
]
type NotRead = Literal["NO_LOST_RUN", "UNQUALIFIED", "PARALOG_IN_WINDOW"]
type NoRelatives = Literal["RESIDUAL_GROUP", "PARALOGS", "FEWER_THAN_TWO"]
type Run = tuple[int, int]

MIN_RUN = 2
LOW_COMPLEXITY_SHARE = 0.4
LOW_COMPLEXITY_LETTERS = 6
RELATIVES_WITHIN = 0.1


def _low_complexity(window: str) -> bool:
    [(_, top)] = Counter(window).most_common(1)
    return (
        top >= LOW_COMPLEXITY_SHARE * len(window)
        or len(set(window)) <= LOW_COMPLEXITY_LETTERS
    )


def _repeated(source: str, start: int) -> bool:
    window = source[start : start + WINDOW]
    left = source[: max(0, start - WINDOW // 2)]
    right = source[start + WINDOW + WINDOW // 2 :]
    return _low_complexity(window) or any(
        best_identity(window, side) >= FOUND for side in (left, right)
    )


def _closed(starts: list[int]) -> list[Run]:
    if len(starts) < MIN_RUN:
        return []
    return [(starts[0], starts[-1] + WINDOW - 1)]


def missing_runs(source: str, target: str) -> list[tuple[int, int]]:
    runs: list[Run] = []
    starts: list[int] = []
    for i in range(0, len(source) - WINDOW + 1, STEP):
        window = source[i : i + WINDOW]
        if best_identity(window, target) < MISSING and not _repeated(source, i):
            starts.append(i + 1)
            continue
        runs += _closed(starts)
        starts = []
    return runs + _closed(starts)


def _fits(length: int, median: float) -> bool:
    return abs(length - median) <= RELATIVES_WITHIN * median


def tie_break(
    reference_length: int, strain_length: int, relatives: float | None
) -> SideVerdict:
    if relatives is None:
        return "NO_RELATIVES"
    match (
        _fits(reference_length, relatives),
        _fits(strain_length, relatives),
        strain_length < reference_length,
    ):
        case (True, False, True):
            return "STRAIN_SHORT"
        case (False, True, True):
            return "REFERENCE_LONG"
        case _:
            return "UNCLEAR"


def judged_side(
    dna: LengthVerdict,
    reference_length: int,
    strain_length: int,
    relatives: float | None,
) -> SideVerdict:
    if dna != "GENOME_ENCODES":
        return "NOT_JUDGED"
    return tie_break(reference_length, strain_length, relatives)


class Relative(CamelModel):
    model_config = ConfigDict(frozen=True)

    organism: str
    length: int


class StrainRelatives(CamelModel):
    model_config = ConfigDict(frozen=True)

    tier: RelativeTier | None
    members: list[Relative]
    missing: NoRelatives | None
    copies_per_organism: float | None

    @computed
    def median(self) -> float | None:
        if not self.members:
            return None
        return statistics.median(member.length for member in self.members)

    @model_validator(mode="after")
    def _set_or_reason(self) -> Self:
        if (self.tier is None) != (self.missing is not None):
            msg = "a relatives set has a tier, or says why there is none"
            raise ValueError(msg)
        if bool(self.members) == (self.tier is None):
            msg = (
                "a relatives set lists its members only with a tier, "
                "and then lists them"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _copies(self) -> Self:
        residual = self.missing == "RESIDUAL_GROUP"
        copies = self.copies_per_organism
        paralogs = copies is not None and copies != 1
        if residual != (copies is None) or paralogs != (self.missing == "PARALOGS"):
            msg = (
                "a relatives set states its group's copies per organism unless the "
                "group is residual, and says PARALOGS when and only when they are not 1"
            )
            raise ValueError(msg)
        return self


def strain_relatives(
    reference: GeneRow, strain: GeneRow, group: list[GeneRow] | None
) -> StrainRelatives:
    if group is None:
        return StrainRelatives(
            tier=None, members=[], missing="RESIDUAL_GROUP", copies_per_organism=None
        )
    copies = GroupProfile.of(group).copies
    found = relatives_of(reference, strain, group) if copies == 1 else None
    if found is None:
        return StrainRelatives(
            tier=None,
            members=[],
            missing="PARALOGS" if copies != 1 else "FEWER_THAN_TWO",
            copies_per_organism=copies,
        )
    return StrainRelatives(
        tier=found.tier,
        members=[
            Relative(organism=organism, length=length)
            for organism, length in sorted(found.lengths.items())
        ],
        missing=None,
        copies_per_organism=copies,
    )


class StrainCheck(CamelModel):
    model_config = ConfigDict(frozen=True)

    lost: list[tuple[int, int]]
    extra: list[tuple[int, int]]
    dna: LengthCheck
    not_read: NotRead | None
    nearby_paralogs: list[str]
    side: SideVerdict
    relatives: StrainRelatives

    @field_validator("lost", "extra")
    @classmethod
    def _ordered(cls, runs: list[Run]) -> list[Run]:
        for start, end in runs:
            if end < start:
                msg = f"a run ends at {end}, before its start {start}"
                raise ValueError(msg)
        return runs

    @model_validator(mode="after")
    def _read(self) -> Self:
        unread = self.dna.verdict == "NOT_CHECKED"
        if (
            unread != (self.not_read is not None)
            or (self.not_read is None and not self.lost)
            or (self.not_read == "NO_LOST_RUN" and self.lost)
        ):
            msg = (
                "a check reads the strain's genome when and only when the strain "
                "lost a run and nothing stops the read"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _paralogs(self) -> Self:
        if bool(self.nearby_paralogs) != (self.not_read == "PARALOG_IN_WINDOW"):
            msg = (
                "a check names the paralogs in its window when and only when "
                "they stop the read"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _qualified(self) -> Self:
        residual = self.relatives.missing == "RESIDUAL_GROUP"
        if residual != (self.not_read == "UNQUALIFIED"):
            msg = (
                "a pair is unqualified when and only when its group is a residual group"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _side(self) -> Self:
        encoded = self.dna.verdict == "GENOME_ENCODES"
        if encoded == (self.side == "NOT_JUDGED"):
            msg = (
                "a check judges a side when and only when the strain's genome "
                "encodes the run it lost"
            )
            raise ValueError(msg)
        no_median = self.relatives.median is None
        if encoded and (self.side == "NO_RELATIVES") != no_median:
            msg = (
                "a check says no relatives when and only when "
                "it has no relatives median"
            )
            raise ValueError(msg)
        return self


class StrainModelAudit(StrainCheck):
    gene_ids: list[GeneId]
    strain_gene: str
    reference_gene: str
    strain_length: int
    reference_length: int
    code: GeneticCode | None
    code_inferred: bool

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.strain_gene, self.reference_gene])
        return self

    @model_validator(mode="after")
    def _code_read(self) -> Self:
        unread = self.dna.verdict == "NOT_CHECKED"
        if unread != (self.code is None) or (unread and self.code_inferred):
            msg = (
                "a check states the code it read the strain's genome with, "
                "and only then"
            )
            raise ValueError(msg)
        return self
