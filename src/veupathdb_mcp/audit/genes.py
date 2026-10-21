"""One genome's genes and a gene list's proteins, read through WDK reports."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, field_validator
from veupathdb import JSONObject
from veupathdb.errors import WDKError
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

from veupathdb_mcp.gene_lookup import dataset_client

GENE_ATTRIBUTES = (
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
ID_CHUNK = 150
_MAX_RECORDS = 400000
_TRANSCRIPTS_PER_GENE = 8
_PSEUDO: TypeAdapter[bool | Literal["Yes", "No"]] = TypeAdapter(
    bool | Literal["Yes", "No"]
)


class GeneRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    ortholog_group: str
    protein_length: int | None
    name: str
    product: str
    sequence_id: str
    start: int
    end: int
    strand: Literal["+", "-"]
    pseudo: bool
    gene_type: str

    @field_validator("protein_length", mode="before")
    @classmethod
    def _length(cls, value: str | int | None) -> int | None:
        text = str(value or "")
        return int(text) if text.isdigit() else None

    @field_validator("pseudo", mode="before")
    @classmethod
    def _pseudo(cls, value: JsonValue) -> bool:
        return _PSEUDO.validate_python(value, strict=True) in (True, "Yes")

    @classmethod
    def from_record(cls, record: WDKRecordInstance) -> GeneRow:
        ids = {part.name: part.value for part in record.id}
        text = {name: record.attribute_text(name) or "" for name in GENE_ATTRIBUTES}
        return cls.model_validate(
            {
                "gene": ids["gene_source_id"],
                "ortholog_group": text["gene_orthomcl_name"],
                "protein_length": text["protein_length"],
                "name": text["gene_name"],
                "product": text["gene_product"],
                "sequence_id": text["sequence_id"],
                "start": text["gene_start_min"],
                "end": text["gene_end_max"],
                "strand": text["strand_plus_minus"],
                "pseudo": text["is_pseudo"],
                "gene_type": text["gene_type"],
            }
        )


def _complete(answer: WDKAnswer, search_name: str) -> WDKAnswer:
    total = answer.meta.total_count
    if total is None or total > len(answer.records):
        msg = (
            f"WDK {search_name} report served {len(answer.records)} records "
            f"of a total of {total}"
        )
        raise WDKError(msg)
    return answer


def rows_of(answer: WDKAnswer) -> list[GeneRow]:
    best: dict[str, GeneRow] = {}
    for record in answer.records:
        row = GeneRow.from_record(record)
        held = best.get(row.gene)
        if held is None or (row.protein_length or 0) > (held.protein_length or 0):
            best[row.gene] = row
    return list(best.values())


async def genes_of_genome(site_id: str, organism: str) -> list[GeneRow]:
    report: JSONObject = {
        "attributes": list(GENE_ATTRIBUTES),
        "tables": [],
        "pagination": {"offset": 0, "numRecords": _MAX_RECORDS},
    }
    answer = await get_wdk_client(site_id).run_search_report(
        "transcript",
        "GenesByTaxon",
        WDKSearchConfig(parameters={"organism": json.dumps([organism])}),
        report,
    )
    return rows_of(_complete(answer, "GenesByTaxon"))


async def gene_rows(site_id: str, gene_ids: list[str]) -> list[GeneRow]:
    if not gene_ids:
        return []
    answers = await _locus_tag_answers(site_id, gene_ids, list(GENE_ATTRIBUTES))
    return [row for answer in answers for row in rows_of(answer)]


async def proteins_of(site_id: str, gene_ids: list[str]) -> dict[str, str]:
    if not gene_ids:
        return {}
    found: dict[str, str] = {}
    for answer in await _locus_tag_answers(site_id, gene_ids, ["protein_sequence"]):
        for record in answer.records:
            ids = {segment.name: segment.value for segment in record.id}
            gene = ids["gene_source_id"]
            sequence = (record.attribute_text("protein_sequence") or "").rstrip("*")
            if len(sequence) > len(found.get(gene, "")):
                found[gene] = sequence
    return found


async def _locus_tag_answers(
    site_id: str, gene_ids: list[str], attributes: list[str]
) -> list[WDKAnswer]:
    async with dataset_client(site_id) as client:
        return [
            await _locus_tag_answer(
                client, gene_ids[start : start + ID_CHUNK], attributes
            )
            for start in range(0, len(gene_ids), ID_CHUNK)
        ]


async def _locus_tag_answer(
    client: VEuPathDBClient, gene_ids: list[str], attributes: list[str]
) -> WDKAnswer:
    dataset = await StrategyAPI(client).create_dataset(
        WDKDatasetConfigIdList(
            source_type="idList",
            source_content=WDKDatasetIdListContent(ids=gene_ids),
        )
    )
    report: JSONObject = {
        "attributes": list(attributes),
        "tables": [],
        "pagination": {
            "offset": 0,
            "numRecords": len(gene_ids) * _TRANSCRIPTS_PER_GENE,
        },
    }
    answer = await client.run_search_report(
        "transcript",
        "GeneByLocusTag",
        WDKSearchConfig(parameters={"ds_gene_ids": str(dataset)}),
        report,
    )
    return _complete(answer, "GeneByLocusTag")
