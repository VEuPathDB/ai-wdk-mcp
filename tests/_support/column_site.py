from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from tests._support.orthomcl_catalog import orthomcl_record_types, recorded_body
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import StrategyAPI, VEuPathDBClient, WDKRecordType

from veupathdb_mcp.wdk import column_counts

SERVICE = "/plasmo.qa/service"
USER = "42"
STEP = 9
BUILD_STEP = 11
GROUP_STEP = 13
ORGANISMS = {
    "Plasmodium berghei ANKA": 120,
    "Plasmodium falciparum 3D7": 310,
    "Plasmodium knowlesi strain H": 12,
    "Plasmodium vivax P01": 310,
    "Plasmodium yoelii yoelii 17X": 45,
}


def _attribute(
    name: str, display_name: str, data_type: str, reports: list[str]
) -> dict[str, Any]:
    return {
        "isInReport": True,
        "formats": [],
        "truncateTo": 100,
        "displayName": display_name,
        "name": name,
        "isSortable": True,
        "isDisplayable": True,
        "isRemovable": True,
        "columnDataType": data_type,
        "tools": {"reports": reports, "filters": reports},
        "properties": {"organisms": ["P. falciparum"], "specificAttribution": []},
    }


TRANSCRIPT_ATTRIBUTES = [
    _attribute("primary_key", "Gene ID", "STRING", ["byValue"]),
    _attribute("organism", "Organism", "STRING", ["byValue"]),
    _attribute("gene_product", "Product Description", "STRING", ["byValue"]),
    _attribute("exon_count", "# Exons in Gene", "NUMBER", ["byValue"]),
    _attribute("overview", "Overview", "OTHER", []),
]


def transcript_record_type() -> dict[str, Any]:
    body: dict[str, Any] = dict(load_recorded("record_type_build").body)
    body.update(
        urlSegment="transcript",
        displayName="Gene",
        recordIdAttributeName="primary_key",
        attributes=TRANSCRIPT_ATTRIBUTES,
    )
    return body


def organism_counts() -> dict[str, Any]:
    total = sum(ORGANISMS.values())
    return {
        "histogram": [
            {"value": count, "binStart": name, "binEnd": name, "binLabel": name}
            for name, count in sorted(ORGANISMS.items())
        ],
        "statistics": {
            "subsetSize": total,
            "numVarValues": total,
            "numDistinctValues": len(ORGANISMS),
            "numDistinctEntityRecords": total,
            "numMissingCases": 0,
        },
    }


EXON_BINS = [212, 160, 101, 89, 58, 42, 30, 25, 19, 14, 11, 9, 6, 5, 4, 3, 2, 1, 0, 6]


def exon_counts() -> dict[str, Any]:
    bins = []
    for index, count in enumerate(EXON_BINS):
        start, end = f"{1.0 + index}", f"{2.0 + index}"
        bins.append(
            {
                "value": count,
                "binStart": start,
                "binEnd": end,
                "binLabel": f"[{start},{end})",
            }
        )
    total = sum(EXON_BINS)
    return {
        "histogram": bins,
        "statistics": {
            "subsetSize": total,
            "subsetMin": 1.0,
            "subsetMax": 20.0,
            "subsetMean": 3.4,
            "numVarValues": total,
            "numDistinctValues": 19,
            "numDistinctEntityRecords": total,
            "numMissingCases": 0,
        },
    }


class ColumnSite:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.record_types_read: list[str] = []
        self.reports: dict[str, httpx.Response] = {
            "organism": httpx.Response(200, json=organism_counts()),
            "exon_count": httpx.Response(200, json=exon_counts()),
        }

    @staticmethod
    def _step(step_id: str) -> httpx.Response:
        record_type, search = {
            str(BUILD_STEP): ("build", "AllBuilds"),
            str(GROUP_STEP): ("group", "GroupsBySequenceCount"),
        }.get(step_id, ("transcript", "GenesByMolecularWeight"))
        return httpx.Response(
            200,
            json={
                "id": int(step_id),
                "searchName": search,
                "searchConfig": {"parameters": {}},
                "recordClassName": record_type,
                "estimatedSize": 1200,
            },
        )

    @staticmethod
    def _search(name: str) -> httpx.Response:
        if name == "GenesByMolecularWeight":
            return httpx.Response(
                200, json=load_recorded("search_genes_by_molecular_weight").body
            )
        return httpx.Response(
            200,
            json={
                "searchData": {"urlSegment": name, "dynamicAttributes": []},
                "validation": {"level": "DISPLAYABLE", "isValid": True},
            },
        )

    def _answer(self, method: str, parts: list[str]) -> httpx.Response:
        match method, parts:
            case "GET", ["users", "current"]:
                answer = httpx.Response(200, json={"id": int(USER), "isGuest": False})
            case "GET", ["users", user, "steps", step_id] if user == USER:
                answer = self._step(step_id)
            case "GET", ["record-types", "transcript"]:
                answer = httpx.Response(200, json=transcript_record_type())
            case "GET", ["record-types", "group"]:
                answer = httpx.Response(
                    200, json=recorded_body("orthomcl_group_record_type")
                )
            case "GET", ["record-types", "build"]:
                answer = httpx.Response(
                    200, json=load_recorded("record_type_build").body
                )
            case "GET", ["record-types", _, "searches", name]:
                answer = self._search(name)
            case "POST", [
                "users",
                user,
                "steps",
                _,
                "columns",
                column,
                "reports",
                _,
            ] if user == USER:
                answer = self.reports.get(column, httpx.Response(404, text="no column"))
            case _:
                answer = httpx.Response(404, text="no such route")
        return answer

    def __call__(self, request: httpx.Request) -> httpx.Response:
        _, service, path = request.url.path.partition("/service/")
        if not service:
            return httpx.Response(200, text="ok")
        query = request.url.query.decode()
        self.requests.append(f"{request.method} /{path}{'?' + query if query else ''}")
        return self._answer(request.method, path.split("/"))

    def posts(self) -> list[str]:
        return [request for request in self.requests if request.startswith("POST")]

    async def record_types(self, site_id: str) -> list[WDKRecordType]:
        self.record_types_read.append(site_id)
        return orthomcl_record_types()


@pytest.fixture
def column_site(monkeypatch: pytest.MonkeyPatch) -> Iterator[ColumnSite]:
    site = ColumnSite()
    monkeypatch.setattr(column_counts, "get_raw_record_types", site.record_types)
    reset = veupathdb_auth_token_ctx.set("registered-token")
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=site)
        yield site
    veupathdb_auth_token_ctx.reset(reset)


def wire_column_api(monkeypatch: pytest.MonkeyPatch) -> ColumnSite:
    site = ColumnSite()
    client = VEuPathDBClient(f"https://qa.plasmodb.org{SERVICE}")

    def answer(method: str, path: str) -> Any:
        return site(
            httpx.Request(method, f"https://qa.plasmodb.org{SERVICE}{path}")
        ).json()

    async def get(path: str, **_: object) -> Any:
        return answer("GET", path)

    async def post(path: str, **_: object) -> Any:
        return answer("POST", path)

    monkeypatch.setattr(client, "get", get)
    monkeypatch.setattr(client, "post", post)
    api = StrategyAPI(client, user_id=USER)
    monkeypatch.setattr(column_counts, "get_strategy_api", lambda site_id: api)
    monkeypatch.setattr(column_counts, "get_raw_record_types", site.record_types)
    return site
