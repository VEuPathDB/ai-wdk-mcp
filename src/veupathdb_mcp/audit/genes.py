"""A genome's genes, a region's genes, a gene's orthologs and a gene list's proteins,
read through WDK reports and gene records."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal, Self

import pydantic
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)
from veupathdb import JSONObject
from veupathdb.errors import DataParsingError, ValidationError, WDKError
from veupathdb.wdk import (
    StrategyAPI,
    VEuPathDBClient,
    WDKAnswer,
    WDKDatasetConfigIdList,
    WDKDatasetIdListContent,
    WDKRecordInstance,
    WDKSearchConfig,
    get_wdk_client,
)

from veupathdb_mcp.audit.gene_models import gene_record
from veupathdb_mcp.gene_lookup import dataset_client

GENE_ATTRIBUTES = (
    "organism_full",
    "gene_orthomcl_name",
    "protein_length",
    "gene_name",
    "gene_product",
    "sequence_id",
    "gene_start_min",
    "gene_end_max",
    "strand_plus_minus",
    "is_pseudo",
    "gene_type",
)
ORTHOLOG_TABLE = "Orthologs"
REGION_SEARCH = "GenesByLocation"
ID_CHUNK = 150
_LOCUS_TAG = "GeneByLocusTag"
_MAX_RECORDS = 400000
_TRANSCRIPTS_PER_GENE = 8
_PSEUDO: TypeAdapter[bool | Literal["Yes", "No"]] = TypeAdapter(
    bool | Literal["Yes", "No"]
)
_SYNTENIC: TypeAdapter[Literal["yes", "no"]] = TypeAdapter(Literal["yes", "no"])


class GeneRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    organism: str = Field(min_length=1)
    ortholog_group: str
    protein_length: int | None
    name: str
    product: str
    sequence_id: str
    start: int
    end: int
    strand: Literal["+", "-"]
    pseudo: bool | None
    gene_type: str

    @field_validator("protein_length", mode="before")
    @classmethod
    def _length(cls, value: str | int | None) -> int | None:
        text = str(value or "")
        return int(text) if text.isdigit() else None

    @field_validator("pseudo", mode="before")
    @classmethod
    def _pseudo(cls, value: JsonValue) -> bool | None:
        if value is None:
            return None
        return _PSEUDO.validate_python(value, strict=True) in (True, "Yes")

    @classmethod
    def from_record(cls, record: WDKRecordInstance) -> GeneRow:
        ids = {part.name: part.value for part in record.id}
        text = {name: record.attribute_text(name) or "" for name in GENE_ATTRIBUTES}
        return cls.model_validate(
            {
                "gene": ids["gene_source_id"],
                "organism": text["organism_full"],
                "ortholog_group": text["gene_orthomcl_name"],
                "protein_length": text["protein_length"],
                "name": text["gene_name"],
                "product": text["gene_product"],
                "sequence_id": text["sequence_id"],
                "start": text["gene_start_min"],
                "end": text["gene_end_max"],
                "strand": text["strand_plus_minus"],
                "pseudo": record.attribute_text("is_pseudo"),
                "gene_type": text["gene_type"],
            }
        )


class OrthologRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    gene: str = Field(validation_alias="ortho_gene_source_id")
    organism: str = Field(min_length=1)
    syntenic: bool = Field(validation_alias="is_syntenic")

    @field_validator("syntenic", mode="before")
    @classmethod
    def _syntenic(cls, value: JsonValue) -> bool:
        return _SYNTENIC.validate_python(value, strict=True) == "yes"


class _OrthologTable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rows: list[OrthologRow] = Field(validation_alias=ORTHOLOG_TABLE)


class _Region(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: int = Field(ge=1)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end and self.end < self.start:
            msg = f"a region ends at {self.end}, before its start {self.start}"
            raise ValueError(msg)
        return self


def _report(attributes: Sequence[str], count: int) -> JSONObject:
    return {
        "attributes": list(attributes),
        "tables": [],
        "pagination": {"offset": 0, "numRecords": count},
    }


def _complete(answer: WDKAnswer, search_name: str) -> WDKAnswer:
    total = answer.meta.total_count
    if total is None or total > len(answer.records):
        msg = (
            f"WDK {search_name} report served {len(answer.records)} records "
            f"of a total of {total}"
        )
        raise WDKError(msg)
    return answer


def _row(record: WDKRecordInstance, search_name: str) -> GeneRow:
    try:
        return GeneRow.from_record(record)
    except pydantic.ValidationError as exc:
        ids = ", ".join(f"{part.name}={part.value}" for part in record.id)
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors())
        msg = (
            f"the WDK {search_name} report served a record ({ids}) "
            f"that is not a gene row: unreadable {fields}"
        )
        raise DataParsingError(msg) from exc


def rows_of(answer: WDKAnswer, search_name: str) -> list[GeneRow]:
    best: dict[str, GeneRow] = {}
    for record in answer.records:
        row = _row(record, search_name)
        held = best.get(row.gene)
        if held is None or (row.protein_length or 0) > (held.protein_length or 0):
            best[row.gene] = row
    return list(best.values())


async def genes_of_genome(site_id: str, organism: str) -> list[GeneRow]:
    answer = await get_wdk_client(site_id).run_search_report(
        "transcript",
        "GenesByTaxon",
        WDKSearchConfig(parameters={"organism": json.dumps([organism])}),
        _report(GENE_ATTRIBUTES, _MAX_RECORDS),
    )
    return rows_of(_complete(answer, "GenesByTaxon"), "GenesByTaxon")


async def region_answer(
    site_id: str, organism: str, sequence_id: str, start: int, end: int
) -> WDKAnswer:
    try:
        region = _Region(start=start, end=end)
    except ValueError as exc:
        msg = f"the region {start}-{end} of {sequence_id} is not one WDK reads"
        raise ValidationError(detail=msg) from exc
    answer = await get_wdk_client(site_id).run_search_report(
        "transcript",
        REGION_SEARCH,
        WDKSearchConfig(
            parameters={
                "organismSinglePick": json.dumps([organism]),
                "chromosomeOptional": "Choose chromosome",
                "sequenceId": sequence_id,
                "start_point": str(region.start),
                "end_point": str(region.end),
            }
        ),
        _report(GENE_ATTRIBUTES, _MAX_RECORDS),
    )
    return _complete(answer, REGION_SEARCH)


async def genes_in_region(
    site_id: str, organism: str, sequence_id: str, start: int, end: int
) -> list[GeneRow]:
    answer = await region_answer(site_id, organism, sequence_id, start, end)
    return sorted(rows_of(answer, REGION_SEARCH), key=lambda row: row.start)


async def ortholog_table(site_id: str, gene: str) -> list[OrthologRow]:
    record = await gene_record(site_id, gene, [], [ORTHOLOG_TABLE])
    try:
        return _OrthologTable.model_validate(record.tables).rows
    except ValueError as exc:
        msg = (
            f"the gene record of {gene} on {site_id} gives no readable {ORTHOLOG_TABLE}"
        )
        raise DataParsingError(msg) from exc


async def orthologs_of(site_id: str, gene: str) -> list[GeneRow]:
    table = await ortholog_table(site_id, gene)
    asked = sorted({gene, *(row.gene for row in table)})
    rows = await gene_rows(site_id, asked)
    missing = sorted(set(asked) - {row.gene for row in rows})
    if missing:
        msg = (
            f"{site_id} serves no gene row for {', '.join(missing)}, "
            f"named in the orthologs of {gene}"
        )
        raise DataParsingError(msg)
    return rows


async def gene_rows(site_id: str, gene_ids: list[str]) -> list[GeneRow]:
    if not gene_ids:
        return []
    answers = await locus_tag_answers(site_id, gene_ids, GENE_ATTRIBUTES)
    return [row for answer in answers for row in rows_of(answer, _LOCUS_TAG)]


async def proteins_of(site_id: str, gene_ids: list[str]) -> dict[str, str]:
    if not gene_ids:
        return {}
    found: dict[str, str] = {}
    for answer in await locus_tag_answers(site_id, gene_ids, ["protein_sequence"]):
        for record in answer.records:
            ids = {segment.name: segment.value for segment in record.id}
            gene = ids["gene_source_id"]
            sequence = (record.attribute_text("protein_sequence") or "").rstrip("*")
            if len(sequence) > len(found.get(gene, "")):
                found[gene] = sequence
    return found


async def locus_tag_answers(
    site_id: str, gene_ids: list[str], attributes: Sequence[str]
) -> list[WDKAnswer]:
    async with dataset_client(site_id) as client:
        return [
            await _locus_tag_answer(
                client, gene_ids[start : start + ID_CHUNK], attributes
            )
            for start in range(0, len(gene_ids), ID_CHUNK)
        ]


async def _locus_tag_answer(
    client: VEuPathDBClient, gene_ids: list[str], attributes: Sequence[str]
) -> WDKAnswer:
    dataset = await StrategyAPI(client).create_dataset(
        WDKDatasetConfigIdList(
            source_type="idList",
            source_content=WDKDatasetIdListContent(ids=gene_ids),
        )
    )
    answer = await client.run_search_report(
        "transcript",
        _LOCUS_TAG,
        WDKSearchConfig(parameters={"ds_gene_ids": str(dataset)}),
        _report(attributes, len(gene_ids) * _TRANSCRIPTS_PER_GENE),
    )
    return _complete(answer, _LOCUS_TAG)
