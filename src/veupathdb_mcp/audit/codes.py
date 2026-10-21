"""Genetic codes and six-frame translation for gene-model checks."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

_BASES = "TCAG"
_STANDARD = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
_COMPLEMENT = str.maketrans(
    "ACGTRYKMSWBDHVNacgtrykmswbdhvn", "TGCAYRMKSWVHDBNtgcayrmkswvhdbn"
)


class GeneticCode(StrEnum):
    STANDARD = "standard"
    CTG_SERINE = "ctg_serine"
    UGA_TRYPTOPHAN = "uga_tryptophan"
    YEAST_MITOCHONDRIAL = "yeast_mitochondrial"
    INVERTEBRATE_MITOCHONDRIAL = "invertebrate_mitochondrial"


def _table(changes: dict[str, str]) -> dict[str, str]:
    codons = [a + b + c for a in _BASES for b in _BASES for c in _BASES]
    table = dict(zip(codons, _STANDARD, strict=True))
    table.update(changes)
    return table


_TABLES: dict[GeneticCode, dict[str, str]] = {
    GeneticCode.STANDARD: _table({}),
    GeneticCode.CTG_SERINE: _table({"CTG": "S"}),
    GeneticCode.UGA_TRYPTOPHAN: _table({"TGA": "W"}),
    GeneticCode.YEAST_MITOCHONDRIAL: _table(
        {"TGA": "W", "ATA": "M", "CTT": "T", "CTC": "T", "CTA": "T", "CTG": "T"}
    ),
    GeneticCode.INVERTEBRATE_MITOCHONDRIAL: _table(
        {"TGA": "W", "ATA": "M", "AGA": "S", "AGG": "S"}
    ),
}


class Frame(BaseModel):
    model_config = ConfigDict(frozen=True)

    strand: Literal["+", "-"]
    offset: int
    protein: str


def reverse_complement(dna: str) -> str:
    return dna.translate(_COMPLEMENT)[::-1]


def translate(dna: str, code: GeneticCode = GeneticCode.STANDARD) -> str:
    table = _TABLES[code]
    return "".join(table.get(dna[i : i + 3], "X") for i in range(0, len(dna) - 2, 3))


def six_frames(dna: str, code: GeneticCode = GeneticCode.STANDARD) -> list[Frame]:
    reverse = reverse_complement(dna)
    forward = [
        Frame(strand="+", offset=f, protein=translate(dna[f:], code)) for f in range(3)
    ]
    backward = [
        Frame(strand="-", offset=f, protein=translate(reverse[f:], code))
        for f in range(3)
    ]
    return forward + backward


def _reads(codon: str, residue: str, expected: str) -> bool:
    if expected == "U":
        return codon == "TGA" and residue == "*"
    return residue == expected


def _explains(cds: str, protein: str, code: GeneticCode) -> bool:
    residues = "M" + translate(cds, code)[1:]
    if len(residues) == len(protein) + 1 and residues.endswith("*"):
        residues = residues[:-1]
    return len(residues) == len(protein) and all(
        _reads(cds[3 * i : 3 * i + 3], residue, expected)
        for i, (residue, expected) in enumerate(zip(residues, protein, strict=True))
    )


def infer_code(cds: str, protein: str) -> GeneticCode | None:
    if not cds or len(cds) % 3:
        return None
    return next((code for code in GeneticCode if _explains(cds, protein, code)), None)
