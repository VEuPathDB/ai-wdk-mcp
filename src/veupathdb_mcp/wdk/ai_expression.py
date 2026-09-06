"""The site's own AI expression summary for one gene, read and never generated."""

from __future__ import annotations

from pydantic import ConfigDict
from veupathdb.model import CamelModel
from veupathdb.wdk.ai_expression import (
    AiExpressionStatus,
    AiExpressionSummary,
)
from veupathdb.wdk.factory import get_site, get_wdk_client

NO_SUMMARY_ON_THE_SITE = "no summary has been generated on the site for this gene"


class GeneExpressionSummary(CamelModel):
    """What one site holds about one gene's expression.

    ``summary`` is present only when the site generated one. Otherwise
    ``unavailable_reason`` says so, and there is nothing to work around.
    """

    model_config = ConfigDict(frozen=True)

    site_id: str
    gene_id: str
    result_status: AiExpressionStatus
    summary: AiExpressionSummary | None = None
    num_experiments: int = 0
    num_experiments_complete: int = 0
    unavailable_reason: str | None = None


async def get_gene_expression_summary(
    site_id: str, gene_id: str
) -> GeneExpressionSummary:
    """Read *site_id*'s AI expression summary for *gene_id*.

    The gene record's primary key carries the site's project id, which is what
    the reporter validates against.
    """
    site = get_site(site_id)
    identifier = gene_id.strip()
    report = await get_wdk_client(site_id).get_ai_expression_report(
        f"{identifier},{site.project_id}"
    )
    found = report.gene(identifier)
    if found is None:
        return GeneExpressionSummary(
            site_id=site_id,
            gene_id=identifier,
            result_status=AiExpressionStatus.MISSING,
            unavailable_reason=NO_SUMMARY_ON_THE_SITE,
        )
    return GeneExpressionSummary(
        site_id=site_id,
        gene_id=identifier,
        result_status=found.result_status,
        summary=found.expression_summary,
        num_experiments=found.num_experiments,
        num_experiments_complete=found.num_experiments_complete,
        unavailable_reason=(
            None if found.expression_summary else NO_SUMMARY_ON_THE_SITE
        ),
    )
