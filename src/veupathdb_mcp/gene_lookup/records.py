from collections.abc import AsyncIterator
from typing import Annotated, Literal

from pydantic import ConfigDict, Discriminator, Field
from veupathdb import strip_html_tags
from veupathdb.model import CamelModel

from veupathdb_mcp.audit import (
    GeneIdProblem,
    GeneIdRefusal,
    GeneIdRows,
    GeneRow,
    each_named,
)

from .result import GeneResult
from .wdk import GeneResolveResult


class GeneIdFound(CamelModel):
    model_config = ConfigDict(frozen=True)

    outcome: Literal["found"] = "found"
    given: str
    records: list[GeneResult] = Field(min_length=1)


type GeneIdReading = Annotated[GeneIdFound | GeneIdRefusal, Discriminator("outcome")]


def gene_result(row: GeneRow) -> GeneResult:
    name = strip_html_tags(row.name)
    product = strip_html_tags(row.product)
    return GeneResult(
        gene_id=row.gene,
        display_name=name or product or row.gene,
        organism=row.organism,
        product=product,
        gene_name=name,
        gene_type=row.gene_type,
        location=f"{row.sequence_id}:{row.start:,}..{row.end:,}({row.strand})",
    )


def _reading(site_id: str, named: GeneIdRows | GeneIdRefusal) -> GeneIdReading:
    match named:
        case GeneIdRefusal():
            return named
        case GeneIdRows(given=given, rows=[]):
            return GeneIdRefusal(
                given=given,
                problem=GeneIdProblem.NOT_FOUND,
                message=f"{given} names no gene of {site_id}",
            )
        case GeneIdRows(given=given, rows=rows):
            return GeneIdFound(given=given, records=[gene_result(r) for r in rows])


async def _readings(site_id: str, gene_ids: list[str]) -> AsyncIterator[GeneIdReading]:
    async for each in each_named(site_id, gene_ids):
        yield _reading(site_id, each)


async def read_each_gene_id(site_id: str, gene_ids: list[str]) -> list[GeneIdReading]:
    return [reading async for reading in _readings(site_id, gene_ids)]


async def read_gene_ids(site_id: str, gene_ids: list[str]) -> GeneResolveResult:
    records: dict[str, GeneResult] = {}
    async for reading in _readings(site_id, gene_ids):
        match reading:
            case GeneIdRefusal(problem=GeneIdProblem.NOT_FOUND):
                continue
            case GeneIdRefusal(message=message):
                return GeneResolveResult(records=[], total_count=0, error=message)
            case GeneIdFound(records=found):
                records |= {record.gene_id: record for record in found}
    return GeneResolveResult(records=list(records.values()), total_count=len(records))
