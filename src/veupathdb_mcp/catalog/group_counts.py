from veupathdb import JSONObject
from veupathdb.domain.parameters import (
    PHYLETIC_EXPRESSION_PARAM,
    PHYLETIC_EXPRESSION_SEARCH,
    PhyleticTree,
)
from veupathdb.errors import ValidationError
from veupathdb.wdk import WDKSearchConfig, get_wdk_client

from veupathdb_mcp.catalog.phyletic_logic import CALL_SECONDS, refuse
from veupathdb_mcp.catalog.taxonomy import ortho_taxonomy

GROUP_RECORD_TYPE = "group"

COUNT_ONLY: JSONObject = {
    "attributes": ["primary_key"],
    "pagination": {"offset": 0, "numRecords": 0},
}


class GroupCountReports:
    def __init__(self, site_id: str, ceiling: int) -> None:
        self.site_id = site_id
        self.ceiling = ceiling
        self.sent = 0

    async def groups(self, expression: str) -> int:
        if self.sent >= self.ceiling:
            refuse(
                "Finding the largest counts the pattern compares needs more than "
                f"{self.ceiling} count reads, the most the {CALL_SECONDS} s call "
                "budget allows. Narrow the pattern: compare fewer distinct sides."
            )
        self.sent += 1
        answer = await get_wdk_client(self.site_id).run_search_report(
            GROUP_RECORD_TYPE,
            PHYLETIC_EXPRESSION_SEARCH,
            WDKSearchConfig(parameters={PHYLETIC_EXPRESSION_PARAM: expression}),
            COUNT_ONLY,
        )
        return answer.meta.records_returned()


async def site_taxonomy(site_id: str) -> PhyleticTree:
    tree = await ortho_taxonomy(site_id)
    if tree is None:
        raise ValidationError(
            title="The site serves no OrthoMCL taxonomy",
            detail=f"{site_id} serves no OrthoMCL taxonomy, so it has no genome codes.",
        )
    return tree
