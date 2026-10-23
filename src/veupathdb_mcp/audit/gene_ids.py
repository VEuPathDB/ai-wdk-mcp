"""Which genes of a site an id names: the gene record the id reads, else the gene whose
own id or transcript id the site's text search finds."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator
from veupathdb.domain.parameters import WDKTreeBoxVocabNode, collect_leaf_terms
from veupathdb.errors import DataParsingError, VEuPathDBErrorCode, WDKError
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKAnswer, WDKSearchConfig, get_wdk_client

from veupathdb_mcp.audit.genes import GeneRow, report_of
from veupathdb_mcp.audit.record_reads import (
    RECORD_READS_PER_CALL,
    SEVERAL_RECORDS,
    bounded,
    found_row,
    record_proteins,
    record_rows,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error
from veupathdb_mcp.wdk.site_cache import SiteCache

TEXT_SEARCH = "GenesByText"
TEXT_ORGANISMS = "text_search_organism"
ID_FIELDS = ("primary_key",)
MAX_MATCHES = 50
_UNSEARCHED = "*"


class _TextHit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gene_source_id: str | None = None
    source_id: str = ""


class GeneId(CamelModel):
    model_config = ConfigDict(frozen=True)

    given: str
    resolved: str


class GeneIdProblem(StrEnum):
    NOT_FOUND = "notFound"
    SEVERAL_GENES = "severalGenes"
    NOT_AN_ID = "notAnId"
    TOO_MANY_MATCHES = "tooManyMatches"


class GeneIdRefusal(CamelModel):
    model_config = ConfigDict(frozen=True)

    outcome: Literal["refused"] = "refused"
    given: str
    problem: GeneIdProblem
    message: str

    @property
    def payload(self) -> ToolErrorPayload:
        return tool_error(VEuPathDBErrorCode.VALIDATION_ERROR, self.message)


class GeneIdRows(BaseModel):
    model_config = ConfigDict(frozen=True)

    given: str
    rows: list[GeneRow]


class GeneReads(BaseModel):
    model_config = ConfigDict(frozen=True)

    rows: list[GeneRow]
    proteins: dict[str, str]
    inputs: dict[str, list[str]]

    @model_validator(mode="after")
    def _inputs_name_rows(self) -> Self:
        served = {row.gene for row in self.rows}
        unserved = {g for genes in self.inputs.values() for g in genes} - served
        if unserved:
            msg = f"inputs name genes with no row: {', '.join(sorted(unserved))}"
            raise ValueError(msg)
        return self

    def named(self, gene_id: str) -> list[GeneRow]:
        genes = self.inputs.get(gene_id.lower(), [])
        own = [gene for gene in genes if gene.lower() == gene_id.lower()]
        return [row for row in self.rows if row.gene in (own or genes)]


async def _named(site_id: str, gene_id: str) -> list[GeneRow] | GeneIdRefusal:
    try:
        row = await found_row(site_id, gene_id)
    except WDKError as exc:
        if exc.status != SEVERAL_RECORDS:
            raise
        return GeneIdRefusal(
            given=gene_id,
            problem=GeneIdProblem.SEVERAL_GENES,
            message=f"{gene_id} names several genes of {site_id}: {exc.detail}",
        )
    if row is not None:
        return [row]
    return await genes_by_text(site_id, gene_id)


async def _each(
    site_id: str, gene_ids: list[str]
) -> AsyncIterator[GeneIdRows | GeneIdRefusal]:
    for given in gene_ids:
        match await _named(site_id, given):
            case GeneIdRefusal() as refusal:
                yield refusal
            case rows:
                yield GeneIdRows(given=given, rows=rows)


def each_named(
    site_id: str, gene_ids: list[str]
) -> AsyncIterator[GeneIdRows | GeneIdRefusal]:
    bounded(gene_ids, RECORD_READS_PER_CALL, "record reads")
    return _each(site_id, gene_ids)


async def rows_named(site_id: str, gene_ids: list[str]) -> GeneReads | ToolErrorPayload:
    rows: dict[str, GeneRow] = {}
    inputs: dict[str, list[str]] = {}
    async for named in each_named(site_id, gene_ids):
        match named:
            case GeneIdRefusal() as refusal:
                return refusal.payload
            case GeneIdRows(given=given, rows=found):
                inputs[given.lower()] = [row.gene for row in found]
                rows |= {row.gene: row for row in found}
    return GeneReads(rows=list(rows.values()), proteins={}, inputs=inputs)


async def rows_and_proteins(
    site_id: str, gene_ids: list[str]
) -> GeneReads | ToolErrorPayload:
    match await rows_named(site_id, gene_ids):
        case ToolErrorPayload() as refusal:
            return refusal
        case GeneReads() as reads:
            proteins = await record_proteins(site_id, [row.gene for row in reads.rows])
            return GeneReads(rows=reads.rows, proteins=proteins, inputs=reads.inputs)


def check_resolved(ids: list[GeneId], genes: list[str]) -> None:
    resolved = [named.resolved for named in ids]
    if resolved != genes:
        msg = f"geneIds resolve to {resolved}, and the answer names {genes}"
        raise ValueError(msg)


def id_pairs(given: list[str], rows: dict[str, GeneRow]) -> list[GeneId]:
    return [GeneId(given=gene, resolved=rows[gene].gene) for gene in given]


def several(site_id: str, gene_id: str, genes: list[str]) -> GeneIdRefusal:
    return GeneIdRefusal(
        given=gene_id,
        problem=GeneIdProblem.SEVERAL_GENES,
        message=f"{gene_id} names {len(genes)} genes of {site_id}: {', '.join(genes)}",
    )


async def _text_organisms(site_id: str) -> list[str]:
    details = await get_wdk_client(site_id).get_search_details(
        "transcript", TEXT_SEARCH
    )
    spec = next(
        (p for p in details.search_data.parameters or [] if p.name == TEXT_ORGANISMS),
        None,
    )
    match spec.vocabulary if spec else None:
        case WDKTreeBoxVocabNode() as tree:
            return collect_leaf_terms(tree)
        case _:
            msg = (
                f"the {TEXT_SEARCH} search of {site_id} lists no {TEXT_ORGANISMS} tree"
            )
            raise DataParsingError(msg)


_ORGANISMS: SiteCache[list[str]] = SiteCache()


async def text_organisms(site_id: str) -> list[str]:
    return await _ORGANISMS.read(site_id, _text_organisms)


async def text_answer(site_id: str, gene_id: str, organisms: list[str]) -> WDKAnswer:
    return await get_wdk_client(site_id).run_search_report(
        "transcript",
        TEXT_SEARCH,
        WDKSearchConfig(
            parameters={
                "text_expression": gene_id,
                "text_fields": json.dumps(list(ID_FIELDS)),
                TEXT_ORGANISMS: json.dumps(organisms),
                "document_type": "gene",
            }
        ),
        report_of([], MAX_MATCHES),
    )


def matched_genes(answer: WDKAnswer, gene_id: str) -> list[str]:
    wanted = gene_id.lower()
    found: set[str] = set()
    for record in answer.records:
        hit = _TextHit.model_validate({part.name: part.value for part in record.id})
        if hit.gene_source_id is None:
            continue
        own = hit.gene_source_id.split(":", 1)[0].lower()
        if wanted in {own, hit.source_id.lower()}:
            found.add(hit.gene_source_id)
    return sorted(found)


async def genes_by_text(site_id: str, gene_id: str) -> list[GeneRow] | GeneIdRefusal:
    if _UNSEARCHED in gene_id or any(c.isspace() for c in gene_id):
        return GeneIdRefusal(
            given=gene_id,
            problem=GeneIdProblem.NOT_AN_ID,
            message=f"{gene_id} holds a wildcard or a space; a gene id holds neither",
        )
    answer = await text_answer(site_id, gene_id, await text_organisms(site_id))
    total = answer.meta.total_count
    if total is None or total > len(answer.records):
        return GeneIdRefusal(
            given=gene_id,
            problem=GeneIdProblem.TOO_MANY_MATCHES,
            message=f"{gene_id} matches more than {MAX_MATCHES} transcripts of {site_id}",
        )
    matched = matched_genes(answer, gene_id)
    if len(matched) > 1:
        return several(site_id, gene_id, matched)
    return await record_rows(site_id, matched)
