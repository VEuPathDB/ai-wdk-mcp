"""Named genes read by their own gene and transcript records, one record at a time."""

from __future__ import annotations

from collections.abc import Sequence

import pydantic
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from veupathdb.errors import DataParsingError, WDKError
from veupathdb.wdk import WDKRecordInstance, get_site, get_strategy_api

from veupathdb_mcp.audit.gene_models import NO_RECORD, gene_record
from veupathdb_mcp.audit.genes import PROTEIN_ATTRIBUTE, GeneRow

RECORD_READS_PER_CALL = 80
MAX_LIST_IDS = 400
TRANSCRIPT_TABLE = "GeneTranscripts"
TRANSCRIPT_RECORD = "transcript"
SEVERAL_RECORDS = 300
RECORD_ATTRIBUTES = (
    "organism_full",
    "orthomcl_name",
    "name",
    "product",
    "sequence_id",
    "start_min",
    "end_max",
    "strand_plus_minus",
    "is_pseudo",
    "gene_type",
)


class _Transcript(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    transcript_id: str = Field(min_length=1)
    protein_length: int | None = None

    @field_validator("protein_length", mode="before")
    @classmethod
    def _length(cls, value: str | int | None) -> int | None:
        text = str(value or "")
        return int(text) if text.isdigit() else None


class _Transcripts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rows: list[_Transcript] = Field(validation_alias=TRANSCRIPT_TABLE)

    @property
    def longest(self) -> _Transcript | None:
        coding = [row for row in self.rows if row.protein_length]
        return min(
            coding,
            key=lambda row: (-(row.protein_length or 0), row.transcript_id),
            default=None,
        )


class TooManyIdsError(ToolError):
    def __init__(self, named: int, bound: int, reads: str) -> None:
        self.named = named
        self.bound = bound
        super().__init__(
            f"{named} genes are named; {reads} read at most {bound} at once"
        )


def bounded(gene_ids: Sequence[str], bound: int, reads: str) -> None:
    if len(gene_ids) > bound:
        raise TooManyIdsError(len(gene_ids), bound, reads)


def _key(record: WDKRecordInstance) -> str:
    return next(part.value for part in record.id if part.name == "source_id")


def _transcripts(site_id: str, record: WDKRecordInstance) -> _Transcripts:
    try:
        return _Transcripts.model_validate(record.tables)
    except pydantic.ValidationError as exc:
        msg = (
            f"the gene record of {_key(record)} on {site_id} gives no readable "
            f"{TRANSCRIPT_TABLE}"
        )
        raise DataParsingError(msg) from exc


def record_row(site_id: str, record: WDKRecordInstance) -> GeneRow:
    text = {name: record.attribute_text(name) or "" for name in RECORD_ATTRIBUTES}
    longest = _transcripts(site_id, record).longest
    try:
        return GeneRow.model_validate(
            {
                "gene": _key(record),
                "organism": text["organism_full"],
                "ortholog_group": text["orthomcl_name"],
                "protein_length": longest.protein_length if longest else None,
                "name": text["name"],
                "product": text["product"],
                "sequence_id": text["sequence_id"],
                "start": text["start_min"],
                "end": text["end_max"],
                "strand": text["strand_plus_minus"],
                "pseudo": record.attribute_text("is_pseudo"),
                "gene_type": text["gene_type"],
            }
        )
    except pydantic.ValidationError as exc:
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors())
        msg = (
            f"the gene record of {_key(record)} on {site_id} is not a gene row: "
            f"unreadable {fields}"
        )
        raise DataParsingError(msg) from exc


async def _row(site_id: str, gene: str) -> GeneRow:
    record = await gene_record(
        site_id, gene, list(RECORD_ATTRIBUTES), [TRANSCRIPT_TABLE]
    )
    return record_row(site_id, record)


async def found_row(site_id: str, gene_id: str) -> GeneRow | None:
    try:
        return await _row(site_id, gene_id)
    except WDKError as exc:
        if exc.status == NO_RECORD:
            return None
        raise


async def record_rows(site_id: str, gene_ids: list[str]) -> list[GeneRow]:
    bounded(gene_ids, RECORD_READS_PER_CALL, "record reads")
    return [await _row(site_id, gene) for gene in gene_ids]


async def _protein(site_id: str, gene: str) -> str | None:
    record = await gene_record(site_id, gene, [], [TRANSCRIPT_TABLE])
    longest = _transcripts(site_id, record).longest
    if longest is None:
        return None
    transcript = await get_strategy_api(site_id).get_single_record(
        TRANSCRIPT_RECORD,
        [
            {"name": "gene_source_id", "value": gene},
            {"name": "source_id", "value": longest.transcript_id},
            {"name": "project_id", "value": get_site(site_id).project_id},
        ],
        attributes=[PROTEIN_ATTRIBUTE],
        tables=[],
    )
    return (transcript.attribute_text(PROTEIN_ATTRIBUTE) or "").rstrip("*") or None


async def record_proteins(site_id: str, gene_ids: list[str]) -> dict[str, str]:
    bounded(gene_ids, RECORD_READS_PER_CALL, "record reads")
    proteins: dict[str, str] = {}
    for gene in gene_ids:
        if (protein := await _protein(site_id, gene)) is not None:
            proteins[gene] = protein
    return proteins


async def read_gene_list(site_id: str, gene_ids: list[str]) -> list[GeneRow]:
    bounded(gene_ids, MAX_LIST_IDS, "one list read")
    rows: dict[str, GeneRow] = {}
    for gene in gene_ids:
        if (row := await found_row(site_id, gene)) is not None:
            rows.setdefault(row.gene, row)
    return list(rows.values())
