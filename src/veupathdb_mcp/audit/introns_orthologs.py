"""How the orthologs of other species compare with an annotated protein and its
correction, counted by the twenty-residue windows each ortholog holds."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.windows import FOUND, STEP, WINDOW, best_identity

ORTHOLOG_SPECIES = 8
_KMER = 3


class OrthologProtein(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    species: str
    protein: str


class OrthologSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    named: int
    proteins: list[OrthologProtein]


class OrthologSupport(CamelModel):
    model_config = ConfigDict(frozen=True)

    named: int | None
    read: int | None
    compared: list[str]
    for_corrected: int | None
    for_annotated: int | None
    reason: str | None = None

    @model_validator(mode="after")
    def _counted_or_explained(self) -> Self:
        counts = {
            value is None
            for value in (self.named, self.read, self.for_corrected, self.for_annotated)
        }
        if counts != {self.reason is not None} or (
            self.reason is not None and self.compared
        ):
            msg = "an ortholog count states its numbers, or the reason it has none"
            raise ValueError(msg)
        return self

    @classmethod
    def not_read(cls, reason: str) -> OrthologSupport:
        return cls(
            named=None,
            read=None,
            compared=[],
            for_corrected=None,
            for_annotated=None,
            reason=reason,
        )


def _kmers(protein: str) -> set[str]:
    return {protein[i : i + _KMER] for i in range(len(protein) - _KMER + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def closest_orthologs(
    own: str, candidates: list[OrthologProtein]
) -> list[OrthologProtein]:
    mine = _kmers(own)
    best: dict[str, tuple[float, OrthologProtein]] = {}
    for candidate in candidates:
        similarity = _jaccard(mine, _kmers(candidate.protein))
        if candidate.species not in best or similarity > best[candidate.species][0]:
            best[candidate.species] = (similarity, candidate)
    ranked = sorted(
        best.values(), key=lambda pair: (pair[0], pair[1].gene), reverse=True
    )
    return [candidate for _, candidate in ranked[:ORTHOLOG_SPECIES]]


def _found(protein: str, model: str) -> set[int]:
    return {
        i
        for i in range(0, len(protein) - WINDOW + 1, STEP)
        if best_identity(protein[i : i + WINDOW], model) >= FOUND
    }


def ortholog_support(
    annotated: str, corrected: str, orthologs: OrthologSet
) -> OrthologSupport:
    chosen = closest_orthologs(annotated, orthologs.proteins)
    gained: list[int] = []
    for candidate in chosen:
        old = _found(candidate.protein, annotated)
        new = _found(candidate.protein, corrected)
        gained.append(len(new - old) - len(old - new))
    return OrthologSupport(
        named=orthologs.named,
        read=len(orthologs.proteins),
        compared=[candidate.gene for candidate in chosen],
        for_corrected=sum(g > 0 for g in gained),
        for_annotated=sum(g < 0 for g in gained),
    )
