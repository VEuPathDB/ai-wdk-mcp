"""Which genes of a site an id names: the rows the locus-tag search serves for it, as the
site echoes each input, else the gene whose own id the site's text search finds."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Self

import pydantic
from pydantic import BaseModel, ConfigDict, Field, model_validator
from veupathdb.domain.parameters import WDKTreeBoxVocabNode, collect_leaf_terms
from veupathdb.errors import DataParsingError, VEuPathDBErrorCode
from veupathdb.model import CamelModel
from veupathdb.wdk import (
    WDKAnswer,
    WDKRecordInstance,
    WDKSearchConfig,
    get_wdk_client,
)

from veupathdb_mcp.audit.genes import (
    GENE_ATTRIBUTES,
    LOCUS_TAG,
    PROTEIN_ATTRIBUTE,
    GeneRow,
    gene_rows,
    locus_tag_answers,
    proteins_in,
    report_of,
    rows_of,
)
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error
from veupathdb_mcp.wdk.site_cache import SiteCache

INPUT_ID = "input_id"
LOCATED_ATTRIBUTES = (*GENE_ATTRIBUTES, INPUT_ID)
TEXT_SEARCH = "GenesByText"
TEXT_ORGANISMS = "text_search_organism"
ID_FIELDS = ("primary_key",)
MAX_MATCHES = 50
_UNSEARCHED = "*"


class GeneId(CamelModel):
    model_config = ConfigDict(frozen=True)

    given: str
    resolved: str


class _Echo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_id: str = Field(min_length=1)


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


def _echoed(record: WDKRecordInstance) -> list[str]:
    try:
        echo = _Echo.model_validate(record.attributes).input_id
    except pydantic.ValidationError as exc:
        ids = ", ".join(f"{part.name}={part.value}" for part in record.id)
        msg = f"the WDK {LOCUS_TAG} report served a record ({ids}) with no {INPUT_ID}"
        raise DataParsingError(msg) from exc
    return [given.strip().lower() for given in echo.split(",") if given.strip()]


def reads_of(answers: list[WDKAnswer]) -> GeneReads:
    inputs: dict[str, set[str]] = defaultdict(set)
    for answer in answers:
        for record in answer.records:
            gene = next(p.value for p in record.id if p.name == "gene_source_id")
            for given in _echoed(record):
                inputs[given].add(gene)
    return GeneReads(
        rows=[row for answer in answers for row in rows_of(answer, LOCUS_TAG)],
        proteins=proteins_in(answers),
        inputs={given: sorted(genes) for given, genes in inputs.items()},
    )


async def rows_named(site_id: str, gene_ids: list[str]) -> GeneReads:
    return reads_of(await locus_tag_answers(site_id, gene_ids, LOCATED_ATTRIBUTES))


async def rows_and_proteins(site_id: str, gene_ids: list[str]) -> GeneReads:
    attributes = (*LOCATED_ATTRIBUTES, PROTEIN_ATTRIBUTE)
    return reads_of(await locus_tag_answers(site_id, gene_ids, attributes))


def check_resolved(ids: list[GeneId], genes: list[str]) -> None:
    resolved = [named.resolved for named in ids]
    if resolved != genes:
        msg = f"geneIds resolve to {resolved}, and the answer names {genes}"
        raise ValueError(msg)


def id_pairs(given: list[str], rows: dict[str, GeneRow]) -> list[GeneId]:
    return [GeneId(given=gene, resolved=rows[gene].gene) for gene in given]


def several(site_id: str, gene_id: str, genes: list[str]) -> ToolErrorPayload:
    return tool_error(
        VEuPathDBErrorCode.VALIDATION_ERROR,
        f"{gene_id} names {len(genes)} genes of {site_id}: {', '.join(genes)}",
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
    return sorted(
        {
            part.value
            for record in answer.records
            for part in record.id
            if part.name == "gene_source_id"
            and part.value.split(":", 1)[0].lower() == gene_id.lower()
        }
    )


async def genes_by_text(site_id: str, gene_id: str) -> list[GeneRow] | ToolErrorPayload:
    if _UNSEARCHED in gene_id or any(c.isspace() for c in gene_id):
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{gene_id} holds a wildcard or a space; a gene id holds neither",
        )
    answer = await text_answer(site_id, gene_id, await text_organisms(site_id))
    total = answer.meta.total_count
    if total is None or total > len(answer.records):
        return tool_error(
            VEuPathDBErrorCode.VALIDATION_ERROR,
            f"{gene_id} matches more than {MAX_MATCHES} transcripts of {site_id}",
        )
    matched = matched_genes(answer, gene_id)
    if len(matched) > 1:
        return several(site_id, gene_id, matched)
    return await gene_rows(site_id, matched)
