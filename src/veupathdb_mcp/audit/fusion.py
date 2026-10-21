"""A long protein against its reference: the residues only the long one holds, and
whether a gene beside the reference holds them."""

from __future__ import annotations

from collections import Counter
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator
from veupathdb.errors import DataParsingError
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.genes import GeneRow, contig_sides
from veupathdb_mcp.audit.lengths import is_orthology_group
from veupathdb_mcp.audit.served import LengthScreen
from veupathdb_mcp.audit.strain import Run, missing_runs
from veupathdb_mcp.audit.windows import FOUND, STEP, WINDOW, best_identity
from veupathdb_mcp.computed import computed

type FusionVerdict = Literal["EXTRA_MATCHES_NEIGHBOUR", "EXTRA_UNEXPLAINED", "NO_EXTRA"]

NEIGHBOUR_WINDOWS = 3
NEIGHBOUR_SHARE = 0.4
NEIGHBOURS_EACH_SIDE = 3


def _starts(extra: list[Run]) -> list[int]:
    return [i for a, b in extra for i in range(a - 1, b - WINDOW + 2, STEP)]


def _matches(windows: int, extra_windows: int) -> bool:
    return windows >= NEIGHBOUR_WINDOWS and windows >= NEIGHBOUR_SHARE * extra_windows


class FusionCheck(CamelModel):
    model_config = ConfigDict(frozen=True)

    extra: list[Run]
    partner: str | None
    closest_neighbour: str | None
    neighbour_windows: int = Field(ge=0)

    @computed
    def extra_windows(self) -> int:
        return len(_starts(self.extra))

    @computed
    def verdict(self) -> FusionVerdict:
        if not self.extra_windows:
            return "NO_EXTRA"
        if _matches(self.neighbour_windows, self.extra_windows):
            return "EXTRA_MATCHES_NEIGHBOUR"
        return "EXTRA_UNEXPLAINED"

    @field_validator("extra")
    @classmethod
    def _ordered(cls, runs: list[Run]) -> list[Run]:
        for start, end in runs:
            if end < start:
                msg = f"a run ends at {end}, before its start {start}"
                raise ValueError(msg)
        return runs

    @model_validator(mode="after")
    def _neighbour(self) -> Self:
        if self.partner is not None and self.closest_neighbour is not None:
            msg = "a check names a partner or a closest neighbour, not both"
            raise ValueError(msg)
        named = self.partner is not None or self.closest_neighbour is not None
        if named != (self.neighbour_windows > 0):
            msg = "a check names a neighbour when and only when it holds a window"
            raise ValueError(msg)
        if self.neighbour_windows > self.extra_windows:
            msg = (
                f"a neighbour holds at most the {self.extra_windows} extra windows, "
                f"not {self.neighbour_windows}"
            )
            raise ValueError(msg)
        if (self.partner is not None) != (self.verdict == "EXTRA_MATCHES_NEIGHBOUR"):
            msg = (
                "a check names a partner when and only when the extra residues "
                "match a neighbour"
            )
            raise ValueError(msg)
        return self


def check_fusion(
    member: str, reference: str, neighbours: dict[str, str]
) -> FusionCheck:
    extra = missing_runs(member, reference)
    hits: Counter[str] = Counter()
    for i in _starts(extra):
        window = member[i : i + WINDOW]
        identity, gene = max(
            (
                (best_identity(window, protein), gene)
                for gene, protein in neighbours.items()
            ),
            default=(0.0, ""),
        )
        if identity >= FOUND:
            hits[gene] += 1
    top, count = hits.most_common(1)[0] if hits else (None, 0)
    matched = _matches(count, len(_starts(extra)))
    return FusionCheck(
        extra=extra,
        partner=top if matched else None,
        closest_neighbour=None if matched else top,
        neighbour_windows=count,
    )


def beside(gene: GeneRow, genome: list[GeneRow]) -> list[GeneRow]:
    own = next(
        (
            row
            for row in genome
            if row.gene == gene.gene and row.sequence_id == gene.sequence_id
        ),
        None,
    )
    if own is None:
        msg = (
            f"the genome of {gene.organism} holds no {gene.gene} on {gene.sequence_id}"
        )
        raise DataParsingError(msg)
    left, right = contig_sides(own, genome, NEIGHBOURS_EACH_SIDE)
    return [*left[::-1], *right]


def copies_beside(gene: GeneRow, genome: list[GeneRow], group: str) -> list[str]:
    return [row.gene for row in beside(gene, genome) if row.ortholog_group == group]


class FusionAudit(FusionCheck):
    neighbours: list[str]
    product: str
    partner_group: str | None
    partner_product: str | None
    partner_copies: list[str] | None

    @model_validator(mode="after")
    def _partner_read(self) -> Self:
        for named in (self.partner, self.closest_neighbour):
            if named is not None and named not in self.neighbours:
                msg = f"{named} is not one of the genes read beside the reference"
                raise ValueError(msg)
        partnered = self.partner is not None
        if partnered != (self.partner_group is not None) or partnered != (
            self.partner_product is not None
        ):
            msg = (
                "a check states the partner's group and product when and only "
                "when it names a partner"
            )
            raise ValueError(msg)
        copies_read = partnered and is_orthology_group(self.partner_group or "")
        if copies_read != (self.partner_copies is not None):
            msg = (
                "a check lists the partner's copies beside the gene when and only "
                "when it names a partner in an orthology group"
            )
            raise ValueError(msg)
        return self


class GeneFusionAudit(LengthScreen):
    fusion: FusionAudit | None

    @model_validator(mode="after")
    def _read_when_long(self) -> Self:
        if (self.fusion is not None) != (self.length_class == "LONG"):
            msg = (
                f"a {self.length_class} gene is checked for a fusion only when "
                "its class is LONG"
            )
            raise ValueError(msg)
        return self
