import asyncio
from collections.abc import Callable

import pytest
from veupathdb import JSONObject
from veupathdb.domain.parameters import PhyleticTree
from veupathdb.wdk import WDKAnswer, WDKSearchConfig

from veupathdb_mcp.catalog import group_counts

COUNT_ONLY: JSONObject = {
    "attributes": ["primary_key"],
    "pagination": {"offset": 0, "numRecords": 0},
}


class CountSite:
    def __init__(self, answer: Callable[[str], int]) -> None:
        self.answer = answer
        self.sent: list[str] = []
        self.in_flight = 0
        self.most_in_flight = 0

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        assert (record_type, search_name) == ("group", "GroupsByPhyleticPattern")
        assert report_config == COUNT_ONLY
        expression = search_config.parameters["phyletic_expression"]
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        self.sent.append(expression)
        return WDKAnswer.model_validate(
            {
                "meta": {"totalCount": self.answer(expression), "responseCount": 0},
                "records": [],
            }
        )


def install(
    monkeypatch: pytest.MonkeyPatch,
    answer: Callable[[str], int],
    tree: PhyleticTree,
) -> CountSite:
    site = CountSite(answer)

    async def taxonomy(site_id: str) -> PhyleticTree:
        assert site_id == "orthomcl"
        return tree

    monkeypatch.setattr(group_counts, "ortho_taxonomy", taxonomy)
    monkeypatch.setattr(group_counts, "get_wdk_client", lambda site_id: site)
    return site
