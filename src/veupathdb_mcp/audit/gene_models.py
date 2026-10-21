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


class ModelTable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rows: list[ModelRow] = Field(default=[], validation_alias=MODEL_TABLE)


class _RecordOrganism(BaseModel):
    model_config = ConfigDict(extra="ignore")

    organism: str = Field(validation_alias=ORGANISM_ATTRIBUTE, min_length=1)


class _RecordParts(ModelTable, _RecordOrganism):
    pass


class GeneModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    organism_abbrev: str
    cds: list[CdsPart]

    @classmethod
    def from_record(cls, record: WDKRecordInstance) -> GeneModel:
        parts = _RecordParts.model_validate({**record.attributes, **record.tables})
        return cls(organism_abbrev=parts.organism, cds=coding_parts(parts.rows))


def transcript_spans(
    rows: list[ModelRow], kind: str, transcript: str
) -> list[tuple[int, int]]:
    return sorted(
        (row.gm_start, row.gm_end)
        for row in rows
        if row.type == kind and transcript in row.transcript_ids
    )


def longest_transcript(rows: list[ModelRow], kind: str) -> list[tuple[int, int]]:
    lengths: Counter[str] = Counter()
    for row in rows:
        if row.type == kind:
            for transcript in row.transcript_ids:
                lengths[transcript] += row.gm_end - row.gm_start + 1
    if not lengths:
        return []
    longest = min(lengths, key=lambda transcript: (-lengths[transcript], transcript))
    return transcript_spans(rows, kind, longest)


def coding_parts(rows: list[ModelRow]) -> list[CdsPart]:
    return [
        CdsPart(start=start, end=end) for start, end in longest_transcript(rows, "CDS")
    ]


async def gene_record(
    site_id: str, gene: str, attributes: list[str], tables: list[str]
) -> WDKRecordInstance:
    return await get_strategy_api(site_id).get_single_record(
        "gene",
        [
            {"name": "source_id", "value": gene},
            {"name": "project_id", "value": get_site(site_id).project_id},
        ],
        attributes=attributes,
        tables=tables,
    )


async def gene_organism(site_id: str, gene: str) -> str:
    record = await gene_record(site_id, gene, [ORGANISM_ATTRIBUTE], [])
    try:
        return _RecordOrganism.model_validate(record.attributes).organism
    except ValidationError as exc:
        msg = f"the gene record of {gene} on {site_id} gives no {ORGANISM_ATTRIBUTE}"
        raise DataParsingError(msg) from exc


class ModelRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: GeneModel
    rows: list[ModelRow]


async def model_record(site_id: str, gene: str) -> ModelRecord:
    record = await gene_record(site_id, gene, [ORGANISM_ATTRIBUTE], [MODEL_TABLE])
    try:
        parts = _RecordParts.model_validate({**record.attributes, **record.tables})
    except ValidationError as exc:
        msg = (
            f"the gene record of {gene} on {site_id} gives no organismAbbrev "
            f"or no readable {MODEL_TABLE}"
        )
        raise DataParsingError(msg) from exc
    model = GeneModel(organism_abbrev=parts.organism, cds=coding_parts(parts.rows))
    return ModelRecord(model=model, rows=parts.rows)


async def gene_model(site_id: str, gene: str) -> GeneModel:
    return (await model_record(site_id, gene)).model
