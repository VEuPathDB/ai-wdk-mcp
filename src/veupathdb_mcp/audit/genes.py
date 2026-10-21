"""A genome's genes, a region's genes, a gene's orthologs, a gene list's proteins and
the site's organism records, read through WDK reports and gene records."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Literal

import pydantic
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
)
from veupathdb import JSONObject
from veupathdb.errors import DataParsingError
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
PROTEIN_ATTRIBUTE = "protein_sequence"
ORTHOLOG_TABLE = "Orthologs"
GENOME_SEARCH = "GenesByTaxon"
ORGANISM_SEARCH = "GenomeDataTypes"
ID_CHUNK = 150
LOCUS_TAG = "GeneByLocusTag"
_MAX_RECORDS = 400000
_MAX_ORGANISMS = 2000
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


def report_of(attributes: Sequence[str], count: int) -> JSONObject:
    return {
        "attributes": list(attributes),
        "tables": [],
        "pagination": {"offset": 0, "numRecords": count},
    }


def complete_answer(answer: WDKAnswer, search_name: str) -> WDKAnswer:
    total = answer.meta.total_count
    if total is None or total > len(answer.records):
        msg = (
            f"WDK {search_name} report served {len(answer.records)} records "
            f"of a total of {total}"
        )
        raise DataParsingError(msg)
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


def contig_sides(
    gene: GeneRow, genome: list[GeneRow], reach: int
) -> tuple[list[GeneRow], list[GeneRow]]:
    ordered = sorted(
        (row for row in genome if row.sequence_id == gene.sequence_id),
        key=lambda row: (row.start, row.gene),
    )
    key = (gene.start, gene.gene)
    left = [row for row in ordered if (row.start, row.gene) < key]
    right = [row for row in ordered if (row.start, row.gene) > key]
    return left[::-1][:reach], right[:reach]


async def genome_answer(site_id: str, organism: str) -> WDKAnswer:
    answer = await get_wdk_client(site_id).run_search_report(
        "transcript",
        GENOME_SEARCH,
        WDKSearchConfig(parameters={"organism": json.dumps([organism])}),
        report_of(GENE_ATTRIBUTES, _MAX_RECORDS),
    )
    return complete_answer(answer, GENOME_SEARCH)


async def genes_of_genome(site_id: str, organism: str) -> list[GeneRow]:
    answer = await genome_answer(site_id, organism)
    return await asyncio.to_thread(rows_of, answer, GENOME_SEARCH)


async def organism_report(site_id: str, attributes: Sequence[str]) -> WDKAnswer:
    answer = await get_wdk_client(site_id).run_search_report(
        "organism",
        ORGANISM_SEARCH,
        WDKSearchConfig(parameters={}),
        report_of(attributes, _MAX_ORGANISMS),
    )
    return complete_answer(answer, ORGANISM_SEARCH)


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
    return [row for answer in answers for row in rows_of(answer, LOCUS_TAG)]


def proteins_in(answers: list[WDKAnswer]) -> dict[str, str]:
    found: dict[str, tuple[int, str, str]] = {}
    for answer in answers:
        for record in answer.records:
            ids = {segment.name: segment.value for segment in record.id}
            gene = ids["gene_source_id"]
            sequence = (record.attribute_text(PROTEIN_ATTRIBUTE) or "").rstrip("*")
            rank = (-len(sequence), ids["source_id"], sequence)
            if sequence and (gene not in found or rank < found[gene]):
                found[gene] = rank
    return {gene: sequence for gene, (_, _, sequence) in found.items()}


async def proteins_of(site_id: str, gene_ids: list[str]) -> dict[str, str]:
    if not gene_ids:
        return {}
    return proteins_in(await locus_tag_answers(site_id, gene_ids, [PROTEIN_ATTRIBUTE]))


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
        LOCUS_TAG,
        WDKSearchConfig(parameters={"ds_gene_ids": str(dataset)}),
        report_of(attributes, len(gene_ids) * _TRANSCRIPTS_PER_GENE),
    )
    return complete_answer(answer, LOCUS_TAG)
