"""A genome's BUSCO completeness as its organism record serves it, and a site's
genomes ranked by the conserved genes their genome holds but their annotation lacks."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Self

import pydantic
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)
from veupathdb.errors import DataParsingError
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.computed import computed

BUSCO_ATTRIBUTES = (
    "organism_full",
    "busco_protein",
    "busco_genome",
    "busco_lineage_dataset",
)
_SCORE = re.compile(
    r"C:\s*(?P<complete>\d+(?:\.\d+)?)%"
    r"\[S:\s*\d+(?:\.\d+)?%,D:\s*\d+(?:\.\d+)?%\],"
    r"F:\s*(?P<fragmented>\d+(?:\.\d+)?)%,"
    r"M:\s*(?P<missing>\d+(?:\.\d+)?)%,"
    r"n:(?P<total>\d+)"
)


class BuscoScore(CamelModel):
    model_config = ConfigDict(frozen=True)

    complete: float = Field(ge=0, le=100)
    fragmented: float = Field(ge=0, le=100)
    missing: float = Field(ge=0, le=100)
    total: int = Field(gt=0)


class GenomePriority(CamelModel):
    model_config = ConfigDict(frozen=True)

    organism: str = Field(min_length=1)
    protein: BuscoScore
    genome: BuscoScore
    lineage: str = Field(min_length=1)

    @computed
    def gap(self) -> float:
        return round(self.genome.complete - self.protein.complete, 1)


class GenomePriorities(CamelModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    genomes: list[GenomePriority]


class OrganismScores(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    organism: str = Field(validation_alias="organism_full", min_length=1)
    protein: BuscoScore | None = Field(validation_alias="busco_protein")
    genome: BuscoScore | None = Field(validation_alias="busco_genome")
    lineage: str | None = Field(validation_alias="busco_lineage_dataset")

    @field_validator("protein", "genome", mode="before")
    @classmethod
    def _served(cls, value: JsonValue) -> dict[str, str] | None:
        match value:
            case None | "":
                return None
            case str() if found := _SCORE.fullmatch(value.strip()):
                return found.groupdict()
            case _:
                msg = f"{value!r} is not a BUSCO score"
                raise ValueError(msg)

    @model_validator(mode="after")
    def _lineage(self) -> Self:
        if self.protein and self.genome and not self.lineage:
            msg = f"{self.organism} has both BUSCO scores but names no BUSCO lineage"
            raise ValueError(msg)
        return self

    @property
    def priority(self) -> GenomePriority | None:
        match self:
            case OrganismScores(
                protein=BuscoScore() as protein,
                genome=BuscoScore() as genome,
                lineage=str() as lineage,
            ):
                return GenomePriority(
                    organism=self.organism,
                    protein=protein,
                    genome=genome,
                    lineage=lineage,
                )
            case _:
                return None


def _scores(record: WDKRecordInstance) -> OrganismScores:
    try:
        return OrganismScores.model_validate(record.attributes)
    except pydantic.ValidationError as exc:
        ids = ", ".join(f"{part.name}={part.value}" for part in record.id)
        fields = ", ".join(
            str(error["loc"][0]) if error["loc"] else error["msg"]
            for error in exc.errors()
        )
        msg = (
            f"the organism report served a record ({ids}) with unreadable "
            f"BUSCO scores: {fields}"
        )
        raise DataParsingError(msg) from exc


def ranked_genomes(records: Sequence[WDKRecordInstance]) -> list[GenomePriority]:
    found = [
        priority
        for record in records
        if (priority := _scores(record).priority) is not None
    ]
    return sorted(found, key=lambda priority: (-priority.gap, priority.organism))
