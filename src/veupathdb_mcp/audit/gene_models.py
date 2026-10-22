"""A gene's organism and coding parts, read from its WDK gene record."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from veupathdb.errors import DataParsingError
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKRecordInstance, get_site, get_strategy_api

from veupathdb_mcp.audit.pseudogene import CdsPart

MODEL_TABLE = "GeneModelDump"
ORGANISM_ATTRIBUTE = "organismAbbrev"
MODEL_READS_PER_FINDING = 2

type Span = tuple[int, int]
type Strand = Literal["+", "-"]


class ModelRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str
    transcript_ids: frozenset[str]
    sequence_id: str
    strand: Strand
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


def longest_of(rows: list[ModelRow], kind: str) -> str | None:
    lengths: Counter[str] = Counter()
    for row in rows:
        if row.type == kind:
            for transcript in row.transcript_ids:
                lengths[transcript] += row.gm_end - row.gm_start + 1
    if not lengths:
        return None
    return min(lengths, key=lambda transcript: (-lengths[transcript], transcript))


def longest_transcript(rows: list[ModelRow], kind: str) -> list[tuple[int, int]]:
    longest = longest_of(rows, kind)
    return [] if longest is None else transcript_spans(rows, kind, longest)


def coding_parts(rows: list[ModelRow]) -> list[CdsPart]:
    return [
        CdsPart(start=start, end=end) for start, end in longest_transcript(rows, "CDS")
    ]


class ModelSpans(CamelModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    transcript: str
    seqid: str
    strand: Strand
    exons: list[Span] = Field(min_length=1)
    cds: list[Span] = Field(min_length=1)


class GeneSpan(CamelModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    seqid: str
    strand: Strand
    start: int
    end: int


def check_models(models: Sequence[ModelSpans | None], genes: list[str]) -> None:
    if not models:
        return
    named = [model.gene if model else None for model in models]
    if len(named) != len(genes) or any(
        name not in {None, gene} for name, gene in zip(named, genes, strict=True)
    ):
        msg = f"the gene models name {named}, and the answer judges {genes}"
        raise ValueError(msg)


class TranscriptParts(BaseModel):
    model_config = ConfigDict(frozen=True)

    transcript: str
    exons: list[Span]
    cds: list[Span] = Field(min_length=1)


def transcript_parts(rows: list[ModelRow]) -> TranscriptParts | None:
    transcript = longest_of(rows, "CDS")
    if transcript is None:
        return None
    return TranscriptParts(
        transcript=transcript,
        exons=transcript_spans(rows, "Exon", transcript),
        cds=transcript_spans(rows, "CDS", transcript),
    )


def no_exon_row(gene: str, transcript: str) -> str:
    return f"the {MODEL_TABLE} of {gene} gives no Exon row for {transcript}"


def read_spans(gene: str, rows: list[ModelRow]) -> ModelSpans | str:
    parts = transcript_parts(rows)
    if parts is None:
        return f"the {MODEL_TABLE} of {gene} gives no CDS row"
    transcript = parts.transcript
    if not parts.exons:
        return no_exon_row(gene, transcript)
    placed = {
        (row.sequence_id, row.strand)
        for row in rows
        if transcript in row.transcript_ids and row.type in {"CDS", "Exon"}
    }
    if len(placed) != 1:
        return (
            f"the {MODEL_TABLE} rows of {gene} lie on more than one strand or sequence"
        )
    [(seqid, strand)] = placed
    return ModelSpans(
        gene=gene,
        transcript=transcript,
        seqid=seqid,
        strand=strand,
        exons=parts.exons,
        cds=parts.cds,
    )


def model_spans(gene: str, rows: list[ModelRow]) -> ModelSpans:
    match read_spans(gene, rows):
        case ModelSpans() as spans:
            return spans
        case reason:
            raise DataParsingError(reason)


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

    gene: str
    model: GeneModel
    rows: list[ModelRow]

    @property
    def spans(self) -> ModelSpans:
        return model_spans(self.gene, self.rows)


class ReadModels(CamelModel):
    model_config = ConfigDict(frozen=True)

    models: list[ModelSpans | None] = Field(default_factory=list)
    evidence_unread: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _a_reason_for_each_model_not_read(self) -> Self:
        if len(self.evidence_unread) != self.models.count(None):
            msg = "each gene model not read needs one reason, and only those"
            raise ValueError(msg)
        return self

    @classmethod
    def of(cls, records: list[ModelRecord]) -> ReadModels:
        models: list[ModelSpans | None] = []
        unread: list[str] = []
        for record in records:
            match read_spans(record.gene, record.rows):
                case ModelSpans() as spans:
                    models.append(spans)
                case reason:
                    models.append(None)
                    unread.append(reason)
        return cls(models=models, evidence_unread=unread)


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
    return ModelRecord(gene=gene, model=model, rows=parts.rows)


async def gene_model(site_id: str, gene: str) -> GeneModel:
    return (await model_record(site_id, gene)).model


class ModelReads:
    def __init__(self, site_id: str) -> None:
        self._site_id = site_id
        self._read = 0

    async def read(self, gene: str) -> ModelRecord:
        if self._read == MODEL_READS_PER_FINDING:
            msg = (
                f"a check reads at most {MODEL_READS_PER_FINDING} gene models "
                f"beside its own reads; {gene} would be one more"
            )
            raise ValueError(msg)
        self._read += 1
        return await model_record(self._site_id, gene)
