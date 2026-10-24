from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from veupathdb import JSONObject
from veupathdb.domain.parameters import PhyleticTree
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKAnswer, WDKSearchConfig, ortho_taxonomy_of

from veupathdb_mcp.catalog import group_counts
from veupathdb_mcp.catalog.group_counts import COUNT_ONLY
from veupathdb_mcp.testing import ORTHOMCL_GROUP_CLOUDS
from veupathdb_mcp.wdk import group_clouds

CLOUD_PATH = "/record-types/sequence/searches/ByTaxonomy/reports/group_link-wordCloud"

type Codes = frozenset[str]


class SetCodes(BaseModel):
    model_config = ConfigDict(frozen=True)

    tox: tuple[str, ...]
    plas: tuple[str, ...]


def recorded(name: str) -> JsonValue:
    raw: JsonValue = json.loads((ORTHOMCL_GROUP_CLOUDS / f"{name}.json").read_text())
    return raw


def recorded_path(name: str) -> Path:
    return ORTHOMCL_GROUP_CLOUDS / f"{name}.json"


def set_codes() -> SetCodes:
    return SetCodes.model_validate_json(recorded_path("codes").read_text())


class _Tag(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    word: str
    count: int


class _Tags(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    tags: tuple[_Tag, ...]


def cloud_counts(name: str) -> Counter[str]:
    tags = _Tags.model_validate(recorded(name)).tags
    return Counter({tag.word: tag.count for tag in tags})


def total_of(name: str) -> int:
    return WDKAnswer.model_validate(recorded(name)).meta.records_returned()


def cloud_body(counts: Mapping[str, int]) -> JsonValue:
    return {"tags": [{"count": count, "word": word} for word, count in counts.items()]}


def recorded_tree() -> PhyleticTree:
    tree = ortho_taxonomy_of(
        WDKAnswer.model_validate(load_recorded("orthomcl_taxonomy").body)
    )
    assert tree is not None
    return tree


def _answer(total: int) -> WDKAnswer:
    return WDKAnswer.model_validate(
        {"meta": {"totalCount": total, "responseCount": 0}, "records": []}
    )


class CloudSite:
    def __init__(
        self,
        clouds: Mapping[Codes, JsonValue],
        records: Mapping[Codes, int],
        groups: Callable[[str], int],
    ) -> None:
        self.clouds = clouds
        self.records = records
        self.groups = groups
        self.sent: list[tuple[str, str]] = []
        self.budgets: list[float | None] = []
        self.in_flight = 0
        self.most_in_flight = 0

    async def _one(self, kind: str, value: str) -> None:
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        self.sent.append((kind, value))

    async def post(
        self, path: str, json: JsonValue = None, *, budget_seconds: float | None = None
    ) -> JsonValue:
        self.budgets.append(budget_seconds)
        assert path == CLOUD_PATH
        body = SentBody.model_validate(json)
        assert body.report_config == {}
        await self._one("cloud", body.search_config.parameters["taxon_type_ahead"])
        return self.clouds[body.codes()]

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
        *,
        budget_seconds: float | None = None,
    ) -> WDKAnswer:
        del budget_seconds
        assert report_config == COUNT_ONLY
        parameters = search_config.parameters
        if record_type == "group":
            assert search_name == "GroupsByPhyleticPattern"
            expression = parameters["phyletic_expression"]
            await self._one("groups", expression)
            return _answer(self.groups(expression))
        assert (record_type, search_name) == ("sequence", "ByTaxonomy")
        value = parameters["taxon_type_ahead"]
        await self._one("records", value)
        return _answer(self.records[frozenset(json.loads(value))])

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.sent]


class _SentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    parameters: dict[str, str]


class SentBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    search_config: _SentConfig = Field(alias="searchConfig")
    report_config: JSONObject = Field(alias="reportConfig")

    def codes(self) -> Codes:
        return frozenset(json.loads(self.search_config.parameters["taxon_type_ahead"]))


def serve_clouds(
    monkeypatch: pytest.MonkeyPatch, site: CloudSite, tree: PhyleticTree
) -> CloudSite:
    async def taxonomy(site_id: str) -> PhyleticTree:
        assert site_id == "orthomcl"
        return tree

    monkeypatch.setattr(group_counts, "ortho_taxonomy", taxonomy)
    monkeypatch.setattr(group_counts, "get_wdk_client", lambda site_id: site)
    monkeypatch.setattr(group_clouds, "get_wdk_client", lambda site_id: site)
    return site
