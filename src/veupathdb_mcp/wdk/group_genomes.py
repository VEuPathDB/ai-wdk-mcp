"""The proteins an OrthoMCL group holds in each genome, read from its TaxonCounts table."""

from collections import Counter
from collections.abc import Sequence
from typing import Self

import pydantic
from pydantic import ConfigDict, Field, model_validator
from veupathdb.errors import DataParsingError
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKRecordInstance

GROUP_GENOME_TABLE = "TaxonCounts"

_GROUP_ID_PART = "group_name"


class GenomeProteins(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    genome: str = Field(validation_alias="abbrev")
    proteins: int = Field(validation_alias="count", ge=1)


class GroupGenomeCounts(CamelModel):
    model_config = ConfigDict(frozen=True)

    group: str
    genomes: tuple[GenomeProteins, ...]

    @model_validator(mode="after")
    def _one_row_per_genome_present(self) -> Self:
        if not self.genomes:
            msg = "the group holds no genome"
            raise ValueError(msg)
        named = Counter(row.genome for row in self.genomes)
        repeated = sorted(genome for genome, times in named.items() if times > 1)
        if repeated:
            msg = f"the table names a genome more than once: {repeated}"
            raise ValueError(msg)
        return self

    @property
    def proteins(self) -> dict[str, int]:
        return {row.genome: row.proteins for row in self.genomes}


def _group_name(record: WDKRecordInstance) -> str:
    for part in record.id:
        if part.name == _GROUP_ID_PART:
            return part.value
    msg = f"a group record carries no {_GROUP_ID_PART} id part"
    raise DataParsingError(msg)


def _group_counts(record: WDKRecordInstance) -> GroupGenomeCounts:
    group = _group_name(record)
    if GROUP_GENOME_TABLE not in record.tables:
        msg = f"group {group} carries no {GROUP_GENOME_TABLE} table"
        raise DataParsingError(msg)
    try:
        return GroupGenomeCounts.model_validate(
            {"group": group, "genomes": record.tables[GROUP_GENOME_TABLE]}
        )
    except pydantic.ValidationError as exc:
        reasons = "; ".join(error["msg"] for error in exc.errors())
        msg = f"group {group} {GROUP_GENOME_TABLE} table is not readable: {reasons}"
        raise DataParsingError(msg) from exc


def group_genome_counts(
    records: Sequence[WDKRecordInstance],
) -> list[GroupGenomeCounts]:
    return [_group_counts(record) for record in records]
