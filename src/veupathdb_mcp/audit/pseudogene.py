"""Whether a pseudogene call sits on a gene whose coding sequence is one intact frame."""

from __future__ import annotations

import difflib
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement, translate

type PseudogeneVerdict = Literal[
    "INTACT", "FRAMESHIFT", "PREMATURE_STOP", "START_OR_STOP_LOST", "NOT_ALIGNED"
]

_COVERED = 0.9


class CdsPart(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: int
    end: int

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            msg = f"the CDS part {self.start}-{self.end} ends before it starts"
            raise ValueError(msg)
        return self


class ReferenceGene(BaseModel):
    model_config = ConfigDict(frozen=True)

    dna: str
    cds: list[CdsPart]
    start: int
    end: int
    strand: Literal["+", "-"]

    @model_validator(mode="after")
    def _spans(self) -> Self:
        length = self.end - self.start + 1
        if len(self.dna) != length:
            msg = (
                f"the reference DNA holds {len(self.dna)} bases for a {length} base "
                f"region {self.start}-{self.end}"
            )
            raise ValueError(msg)
        return self

    @property
    def coding_strand(self) -> str:
        return self.dna if self.strand == "+" else reverse_complement(self.dna)

    @property
    def coding_mask(self) -> list[bool]:
        length = self.end - self.start + 1
        positions = [
            self.start + i if self.strand == "+" else self.end - i
            for i in range(length)
        ]
        return [any(p.start <= g <= p.end for p in self.cds) for g in positions]


class PseudogeneCheck(CamelModel):
    model_config = ConfigDict(frozen=True)

    verdict: PseudogeneVerdict
    reference_cds_length: int
    strain_cds_length: int
    covered: int
    premature_stops: list[int]
    residue_differences: int


def _strain_coding(reference: str, mask: list[bool], strain: str) -> tuple[str, int]:
    pieces: list[str] = []
    covered = 0
    matcher = difflib.SequenceMatcher(None, reference, strain, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                if mask[i1 + k]:
                    pieces.append(strain[j1 + k])
                    covered += op == "equal"
        elif (op == "insert" and 0 < i1 < len(mask) and mask[i1 - 1] and mask[i1]) or (
            op == "replace" and any(mask[i1:i2])
        ):
            pieces.append(strain[j1:j2])
    return "".join(pieces), covered


def _residue_differences(reference: str, strain: str) -> int:
    matcher = difflib.SequenceMatcher(None, reference, strain, autojunk=False)
    return sum(
        max(i2 - i1, j2 - j1)
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
        if op != "equal"
    )


def _verdict(
    covered: int, coding: int, strain_coding: str, protein: str, stops: list[int]
) -> PseudogeneVerdict:
    if covered < _COVERED * coding:
        return "NOT_ALIGNED"
    if len(strain_coding) % 3:
        return "FRAMESHIFT"
    if stops:
        return "PREMATURE_STOP"
    if not protein.startswith("M") or not protein.endswith("*"):
        return "START_OR_STOP_LOST"
    return "INTACT"


def check_pseudogene_call(
    reference: ReferenceGene, strain_dna: str, code: GeneticCode
) -> PseudogeneCheck:
    mask = reference.coding_mask
    reference_dna = reference.coding_strand
    reference_coding = "".join(
        b for b, keep in zip(reference_dna, mask, strict=True) if keep
    )
    strain_coding, covered = _strain_coding(reference_dna, mask, strain_dna)
    protein = translate(strain_coding, code)
    body = protein.removesuffix("*")
    stops = [i + 1 for i, residue in enumerate(body) if residue == "*"]
    return PseudogeneCheck(
        verdict=_verdict(covered, sum(mask), strain_coding, protein, stops),
        reference_cds_length=len(reference_coding),
        strain_cds_length=len(strain_coding),
        covered=covered,
        premature_stops=stops[:20],
        residue_differences=_residue_differences(
            translate(reference_coding, code), protein
        ),
    )
