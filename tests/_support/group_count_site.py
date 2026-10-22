import asyncio
from collections.abc import Callable

import pytest
from pydantic import BaseModel, ConfigDict
from veupathdb import JSONObject
from veupathdb.domain.parameters import PhyleticExpression, PhyleticTree
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKAnswer, WDKSearchConfig, ortho_taxonomy_of

from veupathdb_mcp.catalog import group_counts
from veupathdb_mcp.testing import ORTHOMCL_COUNTS

LADDER_FILE = ORTHOMCL_COUNTS / "orthomcl_protein_count_ladder.json"
CLADE_ONLY_FILE = ORTHOMCL_COUNTS / "orthomcl_clade_only_counts.json"
COUNT_ONLY: JSONObject = {
    "attributes": ["primary_key"],
    "pagination": {"offset": 0, "numRecords": 0},
}


class RecordedReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    expression: str
    total: int


class CountRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    build: str
    search: str
    reports: tuple[RecordedReport, ...]


def recorded_ladder() -> CountRecording:
    return CountRecording.model_validate_json(LADDER_FILE.read_text())


def recorded_clade_only() -> CountRecording:
    return CountRecording.model_validate_json(CLADE_ONLY_FILE.read_text())


def recording(name: str) -> CountRecording:
    return CountRecording.model_validate_json((ORTHOMCL_COUNTS / name).read_text())


def recorded_taxonomy() -> PhyleticTree:
    tree = ortho_taxonomy_of(
        WDKAnswer.model_validate(load_recorded("orthomcl_taxonomy").body)
    )
    assert tree is not None
    return tree


type Reading = frozenset[frozenset[tuple[frozenset[str], str, int, bool]]]


def site_reading(expression: str) -> Reading:
    root = PhyleticExpression.parse(expression).site_reading().root
    return frozenset(
        frozenset(
            (frozenset(unit.codes), unit.op, unit.count, unit.taxa)
            for unit in PhyleticExpression(root=term).units()
        )
        for term in root.operands("OR")
    )


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


def replayed(reports: tuple[RecordedReport, ...]) -> Callable[[str], int]:
    pending = list(reports)

    def answer(expression: str) -> int:
        assert pending, "the comparison sent more reports than the recording holds"
        recorded = pending.pop(0)
        assert site_reading(expression) == site_reading(recorded.expression)
        return recorded.total

    return answer


def install(monkeypatch: pytest.MonkeyPatch, answer: Callable[[str], int]) -> CountSite:
    site = CountSite(answer)
    tree = recorded_taxonomy()

    async def taxonomy(site_id: str) -> PhyleticTree:
        assert site_id == "orthomcl"
        return tree

    monkeypatch.setattr(group_counts, "ortho_taxonomy", taxonomy)
    monkeypatch.setattr(group_counts, "get_wdk_client", lambda site_id: site)
    return site


def install_recorded(monkeypatch: pytest.MonkeyPatch) -> CountSite:
    return install(monkeypatch, replayed(recorded_ladder().reports))


def install_replay(
    monkeypatch: pytest.MonkeyPatch, recorded: CountRecording
) -> CountSite:
    return install(monkeypatch, replayed(recorded.reports))


def install_recorded_clade_only(monkeypatch: pytest.MonkeyPatch) -> CountSite:
    return install(monkeypatch, replayed(recorded_clade_only().reports))
