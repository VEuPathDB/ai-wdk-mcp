import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from scripts.record_audit_fixtures import act_as_the_test_account
from veupathdb import JSONObject
from veupathdb.devtools import use_qa_sites
from veupathdb.domain.parameters import PHYLETIC_EXPRESSION_PARAM
from veupathdb.model import CamelModel
from veupathdb.wdk import (
    VEuPathDBClient,
    WDKAnswer,
    WDKSearchConfig,
    close_all_clients,
    get_wdk_client,
)

from veupathdb_mcp.catalog import group_counts
from veupathdb_mcp.catalog.clade_only import every_species_expression
from veupathdb_mcp.testing import ORTHOMCL_COUNTS

SITE = "orthomcl"
SEARCH = "GroupsByPhyleticPattern"
FILE = "orthomcl_every_species_counts.json"
CRYPTOSPORIDIUM = [
    "cand",
    "cbov",
    "choi",
    "chot",
    "chom",
    "chod",
    "cmel",
    "cmtu",
    "cmur",
    "cpia",
    "cpib",
    "cpar",
    "crya",
    "cser",
    "cspi",
    "cscp",
    "ctyz",
    "cubi",
]
REPORT_BUDGET = 1


class CountReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    expression: str
    total: int


class Recording(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    build: str
    search: str
    reports: tuple[CountReport, ...]


class _ServiceRoot(CamelModel):
    model_config = ConfigDict(extra="ignore")

    build_number: str


class CountTape:
    def __init__(self, client: VEuPathDBClient, budget: int) -> None:
        self._client = client
        self._budget = budget
        self.reports: list[CountReport] = []

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        if search_name != SEARCH or len(self.reports) >= self._budget:
            msg = f"the recording allows {self._budget} {SEARCH} count reports"
            raise RuntimeError(msg)
        answer = await self._client.run_search_report(
            record_type, search_name, search_config, report_config
        )
        expression = search_config.parameters[PHYLETIC_EXPRESSION_PARAM]
        total = answer.meta.records_returned()
        print("count", expression, total)
        self.reports.append(CountReport(expression=expression, total=total))
        return answer


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    client = get_wdk_client(SITE)
    tape = CountTape(client, REPORT_BUDGET)
    group_counts.get_wdk_client = lambda site_id: tape
    try:
        build = _ServiceRoot.model_validate(await client.get("/")).build_number
        print("build", build)
        result = await every_species_expression(SITE, CRYPTOSPORIDIUM)
        print("groups", result.groups)
    finally:
        await close_all_clients()
    recording = Recording(
        site=SITE, build=build, search=SEARCH, reports=tuple(tape.reports)
    )
    into.mkdir(parents=True, exist_ok=True)
    (into / FILE).write_text(recording.model_dump_json(indent=1) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ORTHOMCL_COUNTS)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.out))
