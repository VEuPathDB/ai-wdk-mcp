from veupathdb import strip_html_tags

from veupathdb_mcp.audit import GeneReads, GeneRow, rows_named
from veupathdb_mcp.tool_errors import ToolErrorPayload

from .result import GeneResult
from .wdk import GeneResolveResult


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


async def read_gene_ids(site_id: str, gene_ids: list[str]) -> GeneResolveResult:
    match await rows_named(site_id, gene_ids):
        case ToolErrorPayload() as refusal:
            return GeneResolveResult(records=[], total_count=0, error=refusal.message)
        case GeneReads() as reads:
            records = [gene_result(row) for row in reads.rows]
            return GeneResolveResult(records=records, total_count=len(records))
