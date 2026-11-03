"""What a site's short variant calls say of a strain at one stretch of its reference."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from veupathdb.model import CamelModel

from veupathdb_mcp.computed import computed

VARIANT_RECORD_TYPE = "variation"
VARIANT_SEARCH = "VariantsByLocation"
VARIANT_TABLE = "VariantStrains"
MIN_UNCALLED_HOMOPOLYMER = 7
_ORGANISM_PREFIX = 4
_REFERENCE_GENOTYPE = "0"
_NO_CALL = "No call"

type VariantAnswer = Literal[
    "INDEL_CALLED",
    "NO_INDEL_CALLED",
    "NO_VARIANT_CALLED",
    "NOT_COVERED",
    "NOT_SAMPLED",
]


class StrainCall(CamelModel):
    model_config = ConfigDict(frozen=True)

    variant: str
    genotype: str
    allele: str | None
    depth: str | None
    read_frequency: str | None


class VariantCalls(CamelModel):
    model_config = ConfigDict(frozen=True)

    site: str
    record_type: str = VARIANT_RECORD_TYPE
    search: str = VARIANT_SEARCH
    table: str = VARIANT_TABLE
    organism: str
    seqid: str
    start: int
    end: int
    variants: list[str]
    sample: str | None
    calls: list[StrainCall]
    answer: VariantAnswer
    homopolymer_bases: int | None

    @computed
    def determinable(self) -> bool:
        match self.answer:
            case "INDEL_CALLED":
                return True
            case "NOT_COVERED" | "NOT_SAMPLED":
                return False
            case "NO_INDEL_CALLED" | "NO_VARIANT_CALLED":
                return (self.homopolymer_bases or 0) < MIN_UNCALLED_HOMOPOLYMER


class VariantRow(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, coerce_numbers_to_str=True)

    strain: str
    genotype: str
    allele: str | None = None
    depth: str | None = None
    read_frequency: str | None = None

    def is_indel_against(self, reference_allele: str | None) -> bool:
        if not reference_allele or self.allele is None:
            return False
        if self.genotype in {_REFERENCE_GENOTYPE, _NO_CALL}:
            return False
        return any(
            len(allele) != len(reference_allele) for allele in self.allele.split("/")
        )


class VariantTable(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    rows: list[VariantRow] = Field(validation_alias=VARIANT_TABLE)


class VariantRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant: str
    reference_allele: str | None
    rows: list[VariantRow]


def strain_sample(organism: str, strains: set[str]) -> str | None:
    wanted = organism[_ORGANISM_PREFIX:].casefold()
    return min(
        (strain for strain in strains if strain.split("_")[0].casefold() == wanted),
        default=None,
    )


class ReadCalls(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: VariantAnswer
    sample: str | None
    calls: list[StrainCall]


def judge_calls(organism: str, records: list[VariantRecord]) -> ReadCalls:
    if not records:
        return ReadCalls(answer="NO_VARIANT_CALLED", sample=None, calls=[])
    sample = strain_sample(
        organism, {row.strain for record in records for row in record.rows}
    )
    if sample is None:
        return ReadCalls(answer="NOT_SAMPLED", sample=None, calls=[])
    held = [
        (record, row)
        for record in records
        for row in record.rows
        if row.strain == sample
    ]
    calls = [
        StrainCall(
            variant=record.variant,
            genotype=row.genotype,
            allele=row.allele,
            depth=row.depth,
            read_frequency=row.read_frequency,
        )
        for record, row in held
    ]
    answer: VariantAnswer = "NO_INDEL_CALLED"
    if any(row.is_indel_against(record.reference_allele) for record, row in held):
        answer = "INDEL_CALLED"
    elif all(row.genotype == _NO_CALL for _, row in held):
        answer = "NOT_COVERED"
    return ReadCalls(answer=answer, sample=sample, calls=calls)
