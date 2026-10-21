"""A gene's organism and coding parts, read from its WDK gene record."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from veupathdb.errors import DataParsingError
from veupathdb.wdk import WDKRecordInstance, get_site, get_strategy_api

from veupathdb_mcp.audit.pseudogene import CdsPart

MODEL_TABLE = "GeneModelDump"
ORGANISM_ATTRIBUTE = "organismAbbrev"


class ModelRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str
    transcript_ids: frozenset[str]
    gm_start: int
    gm_end: int

    @field_validator("transcript_ids", mode="before")
    @classmethod
    def _listed(cls, value: str | frozenset[str]) -> frozenset[str]:
        match value:
            case str():
                return frozenset(p.strip() for p in value.split(",") if p.strip())
            case _:
                return value


class _RecordParts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    organism: str = Field(validation_alias=ORGANISM_ATTRIBUTE, min_length=1)
    rows: list[ModelRow] = Field(default=[], validation_alias=MODEL_TABLE)


class GeneModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    organism: str
    cds: list[CdsPart]

    @classmethod
    def from_record(cls, record: WDKRecordInstance) -> GeneModel:
        parts = _RecordParts.model_validate({**record.attributes, **record.tables})
        return cls(organism=parts.organism, cds=coding_parts(parts.rows))


def coding_parts(rows: list[ModelRow]) -> list[CdsPart]:
    cds = [row for row in rows if row.type == "CDS"]
    lengths: Counter[str] = Counter()
    for row in cds:
        for transcript in row.transcript_ids:
            lengths[transcript] += row.gm_end - row.gm_start + 1
    if not lengths:
        return []
    longest = min(lengths, key=lambda transcript: (-lengths[transcript], transcript))
    return [
        CdsPart(start=start, end=end)
        for start, end in sorted(
            (row.gm_start, row.gm_end) for row in cds if longest in row.transcript_ids
        )
    ]


async def gene_model(site_id: str, gene: str) -> GeneModel:
    record = await get_strategy_api(site_id).get_single_record(
        "gene",
        [
            {"name": "source_id", "value": gene},
            {"name": "project_id", "value": get_site(site_id).project_id},
        ],
        attributes=[ORGANISM_ATTRIBUTE],
        tables=[MODEL_TABLE],
    )
    try:
        return GeneModel.from_record(record)
    except ValidationError as exc:
        msg = (
            f"the gene record of {gene} on {site_id} gives no organismAbbrev "
            f"or no readable {MODEL_TABLE}"
        )
        raise DataParsingError(msg) from exc
