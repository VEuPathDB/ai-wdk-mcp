"""A genome's pseudogene calls, each paired with one single-copy coding gene of a
reference genome by ortholog group or by identical product."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.lengths import is_coding, is_orthology_group
from veupathdb_mcp.computed import computed

FAMILY_WORDS = (
    "erythrocyte membrane protein 1",
    "rifin",
    "stevor",
    "phist",
    "surfin",
    "pfmc-2tm",
    "exported protein",
    "unknown function",
    "hypothetical",
    "plasmodium exported",
    "fikk",
    "acyl-coa synthetase",
    "var",
    "early transcribed membrane",
    "etramp",
    "dnaj",
    "lysophospholipase",
    "gbp",
    "erythrocyte binding",
    "reticulocyte binding",
    "clag",
    "sera",
    "ring-infected",
    "knob",
    "msp",
)

type PairBasis = Literal["ORTHOLOG_GROUP", "PRODUCT"]
type Unpaired = Literal["FAMILY_WORD", "NO_REFERENCE", "SEVERAL_REFERENCES"]


class PseudogeneCall(CamelModel):
    model_config = ConfigDict(frozen=True)

    pseudogene: str
    reference_gene: str
    product: str
    basis: PairBasis


class UnpairedPseudogene(CamelModel):
    model_config = ConfigDict(frozen=True)

    pseudogene: str
    reason: Unpaired
    word: str | None

    @model_validator(mode="after")
    def _word(self) -> Self:
        if (self.word is not None) != (self.reason == "FAMILY_WORD"):
            msg = "an unpaired pseudogene names its listed word when and only then"
            raise ValueError(msg)
        return self


class UnpairedCounts(CamelModel):
    model_config = ConfigDict(frozen=True)

    family_word: int = Field(ge=0)
    no_reference: int = Field(ge=0)
    several_references: int = Field(ge=0)


class GenomePseudogeneCalls(CamelModel):
    model_config = ConfigDict(frozen=True)

    organism: str
    reference_organism: str
    genes: int = Field(ge=0)
    pseudogenes: int = Field(ge=0)
    unflagged: int = Field(ge=0)
    reference_genes: int = Field(ge=0)
    reference_unflagged: int = Field(ge=0)
    calls: list[PseudogeneCall]
    unpaired_genes: list[UnpairedPseudogene]

    @model_validator(mode="after")
    def _counts_add_up(self) -> Self:
        if self.pseudogenes + self.unflagged > self.genes:
            msg = (
                f"{self.pseudogenes} pseudogenes and {self.unflagged} unflagged "
                f"genes exceed the {self.genes} genes"
            )
            raise ValueError(msg)
        if self.reference_unflagged > self.reference_genes:
            msg = (
                f"{self.reference_unflagged} unflagged reference genes exceed "
                f"the {self.reference_genes} reference genes"
            )
            raise ValueError(msg)
        left_out = len(self.unpaired_genes)
        if len(self.calls) + left_out != self.pseudogenes:
            msg = (
                f"{len(self.calls)} calls and {left_out} unpaired are not "
                f"the {self.pseudogenes} pseudogenes"
            )
            raise ValueError(msg)
        return self

    @computed
    def no_gene_flagged(self) -> bool:
        return self.unflagged == self.genes > 0

    @computed
    def unpaired(self) -> UnpairedCounts:
        reasons = Counter(gene.reason for gene in self.unpaired_genes)
        return UnpairedCounts(
            family_word=reasons["FAMILY_WORD"],
            no_reference=reasons["NO_REFERENCE"],
            several_references=reasons["SEVERAL_REFERENCES"],
        )


def _family(product: str) -> str | None:
    return next((word for word in FAMILY_WORDS if word in product.lower()), None)


def _orthology_group(row: GeneRow) -> str | None:
    group = row.ortholog_group
    return group if is_orthology_group(group) else None


def _held(
    rows: list[GeneRow], key: Callable[[GeneRow], str]
) -> dict[str, list[GeneRow]]:
    held: defaultdict[str, list[GeneRow]] = defaultdict(list)
    for row in rows:
        held[key(row)].append(row)
    return held


def _left(row: GeneRow, reason: Unpaired, word: str | None) -> UnpairedPseudogene:
    return UnpairedPseudogene(pseudogene=row.gene, reason=reason, word=word)


def _pair(
    row: GeneRow,
    by_group: dict[str, list[GeneRow]],
    by_product: dict[str, list[GeneRow]],
) -> PseudogeneCall | UnpairedPseudogene:
    if (word := _family(row.product)) is not None:
        return _left(row, "FAMILY_WORD", word)
    group = _orthology_group(row)
    basis: PairBasis = "PRODUCT" if group is None else "ORTHOLOG_GROUP"
    held = by_product.get(row.product, []) if group is None else by_group.get(group, [])
    match held:
        case []:
            return _left(row, "NO_REFERENCE", None)
        case [reference] if (word := _family(reference.product)) is not None:
            return _left(row, "FAMILY_WORD", word)
        case [reference]:
            return PseudogeneCall(
                pseudogene=row.gene,
                reference_gene=reference.gene,
                product=row.product,
                basis=basis,
            )
        case _:
            return _left(row, "SEVERAL_REFERENCES", None)


def pseudogene_calls_of(
    organism: str,
    reference_organism: str,
    genome: list[GeneRow],
    reference: list[GeneRow],
) -> GenomePseudogeneCalls:
    coding = [
        row
        for row in reference
        if row.pseudo is False
        and is_coding(row)
        and is_orthology_group(row.ortholog_group)
    ]
    by_group = _held(coding, lambda row: row.ortholog_group)
    by_product = _held(coding, lambda row: row.product)
    calls: list[PseudogeneCall] = []
    unpaired: list[UnpairedPseudogene] = []
    pseudogenes = sorted(
        (row for row in genome if row.pseudo is True), key=lambda row: row.gene
    )
    for row in pseudogenes:
        match _pair(row, by_group, by_product):
            case PseudogeneCall() as call:
                calls.append(call)
            case UnpairedPseudogene() as left:
                unpaired.append(left)
    return GenomePseudogeneCalls(
        organism=organism,
        reference_organism=reference_organism,
        genes=len(genome),
        pseudogenes=len(pseudogenes),
        unflagged=sum(row.pseudo is None for row in genome),
        reference_genes=len(reference),
        reference_unflagged=sum(row.pseudo is None for row in reference),
        calls=calls,
        unpaired_genes=unpaired,
    )
