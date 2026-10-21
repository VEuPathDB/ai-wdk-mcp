"""An id lookup reads at most a fixed number of records per id, and says when an answer holds more."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import respx
from veupathdb.auth_context import veupathdb_auth_token_ctx

from veupathdb_mcp.gene_lookup import TRANSCRIPTS_PER_GENE, resolve_gene_ids

IDS = ["PF3D7_1133400", "PF3D7_0100100"]


def _site(answer: dict[str, Any], reports: list[dict[str, Any]]) -> Callable[..., Any]:
    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/users/current"):
            return httpx.Response(200, json={"id": 42, "isGuest": False})
        if path.endswith("/datasets"):
            return httpx.Response(200, json={"id": 7})
        if path.endswith("/reports/standard"):
            reports.append(json.loads(request.content))
            return httpx.Response(200, json=answer)
        return httpx.Response(200, text="ok")

    return respond


def _answer(total: int, served: int) -> dict[str, Any]:
    return {
        "meta": {"totalCount": total, "responseCount": served},
        "records": [
            {
                "displayName": f"PF3D7_11334{index:02d}",
                "id": [{"name": "gene_source_id", "value": f"PF3D7_11334{index:02d}"}],
                "attributes": {},
            }
            for index in range(served)
        ],
    }


@pytest.fixture
def researcher(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("VEUPATHDB_AUTH_TOKEN", "deployment.account.token")
    reset = veupathdb_auth_token_ctx.set("researcher.registered.token")
    try:
        yield
    finally:
        veupathdb_auth_token_ctx.reset(reset)


@pytest.mark.usefixtures("researcher")
@respx.mock
async def test_the_read_asks_for_a_fixed_number_of_records_per_id() -> None:
    reports: list[dict[str, Any]] = []
    respx.route().mock(side_effect=_site(_answer(2, 2), reports))

    result = await resolve_gene_ids("plasmodb", IDS)

    assert result.error is None
    assert [report["reportConfig"]["pagination"] for report in reports] == [
        {"offset": 0, "numRecords": 2 * TRANSCRIPTS_PER_GENE}
    ]


@pytest.mark.usefixtures("researcher")
@respx.mock
async def test_an_answer_past_the_bound_is_an_error_not_a_short_list() -> None:
    reports: list[dict[str, Any]] = []
    cap = 2 * TRANSCRIPTS_PER_GENE
    respx.route().mock(side_effect=_site(_answer(cap + 1, cap), reports))

    result = await resolve_gene_ids("plasmodb", IDS)

    assert (result.records, result.total_count) == ([], 0)
    assert result.error is not None
    assert f"holds {cap + 1} records" in result.error
