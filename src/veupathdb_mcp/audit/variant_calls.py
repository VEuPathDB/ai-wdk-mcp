from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field
from veupathdb.model import CamelModel

from veupathdb_mcp.computed import computed

VARIANT_RECORD_TYPE = "variation"
VARIANT_SEARCH = "VariantsByLocation"
VARIANT_TABLE = "VariantStrains"
MIN_UNCALLED_HOMOPOLYMER = 7
_ORGANISM_PREFIX = 4
_SNV = "SNV"
_NAME_BREAK = re.compile(r"[^0-9A-Za-z]")


class StrainCall(CamelModel):
    model_config = ConfigDict(frozen=True)

    sample: str
    genotype: str
    allele: str | None
    depth: str | None
    read_frequency: str | None


class VariantSite(CamelModel):
    model_config = ConfigDict(frozen=True)

    variant: str
    variant_type: str | None
    indel_ref_allele: str | None
    indel_frame_effect: str | None
    calls: list[StrainCall]


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
    sites: list[VariantSite]
    samples: list[str]
    homopolymer_bases: int | None

    @computed
    def calls_say_little(self) -> bool:
        return (self.homopolymer_bases or 0) >= MIN_UNCALLED_HOMOPOLYMER and all(
            site.variant_type == _SNV for site in self.sites
        )


class VariantRow(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, coerce_numbers_to_str=True)

    strain: str
    genotype: str
    allele: str | None = None
    depth: str | None = None
    read_frequency: str | None = None


class VariantTable(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    rows: list[VariantRow] = Field(validation_alias=VARIANT_TABLE)


class VariantRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant: str
    variant_type: str | None
    reference_allele: str | None
    frame_effect: str | None
    rows: list[VariantRow]


def _first_name(name: str) -> str:
    return _NAME_BREAK.split(name, maxsplit=1)[0].casefold()


def strain_samples(organism: str, strains: set[str]) -> list[str]:
    wanted = _first_name(organism[_ORGANISM_PREFIX:])
    return sorted(strain for strain in strains if _first_name(strain) == wanted)


def read_sites(
    organism: str, records: list[VariantRecord]
) -> tuple[list[VariantSite], list[str]]:
    samples = strain_samples(
        organism, {row.strain for record in records for row in record.rows}
    )
    return [
        VariantSite(
            variant=record.variant,
            variant_type=record.variant_type,
            indel_ref_allele=record.reference_allele,
            indel_frame_effect=record.frame_effect,
            calls=[
                StrainCall(
                    sample=row.strain,
                    genotype=row.genotype,
                    allele=row.allele,
                    depth=row.depth,
                    read_frequency=row.read_frequency,
                )
                for sample in samples
                for row in record.rows
                if row.strain == sample
            ],
        )
        for record in records
    ], samples
