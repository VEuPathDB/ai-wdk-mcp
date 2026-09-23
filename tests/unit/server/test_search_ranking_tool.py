"""What the served search ranking carries: the relative score and the raw cosine."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

from veupathdb_mcp import server
from veupathdb_mcp.auth import CredentialMode, McpCredential
from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.models import SearchMatch

_CREDENTIAL = McpCredential(
    token="service-secret",
    client_id="gene-page",
    scopes=[],
    mode=CredentialMode.SERVICE,
)


async def _call(arguments: dict[str, Any]) -> dict[str, Any] | None:
    reset = auth_context_var.set(AuthenticatedUser(_CREDENTIAL))
    try:
        async with Client(server.build_server()) as client:
            result = await client.call_tool("search_for_searches", arguments)
    finally:
        auth_context_var.reset(reset)
    return result.structured_content


async def test_each_match_carries_its_relevance_and_its_cosine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ranked(*_a: Any, **_k: Any) -> list[SearchMatch]:
        return [
            SearchMatch(
                name="GenesByExportPrediction",
                display_name="Exported Protein",
                description="",
                record_type="transcript",
                relevance=1.0,
                semantic_similarity=0.21,
            ),
            SearchMatch(
                name="GenesByMolecularWeight",
                display_name="Molecular Weight",
                description="",
                record_type="transcript",
                relevance=0.4,
            ),
        ]

    monkeypatch.setattr(searches, "search_for_searches", ranked)

    content = await _call({"site_id": "plasmodb", "query": "predicted GPI anchor"})

    assert content is not None
    rows = {row["name"]: row for row in content["result"]}
    assert rows["GenesByExportPrediction"]["relevance"] == 1.0
    assert rows["GenesByExportPrediction"]["semantic_similarity"] == 0.21
    assert rows["GenesByMolecularWeight"]["semantic_similarity"] is None


async def test_a_query_nothing_matches_answers_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def nothing(*_a: Any, **_k: Any) -> list[SearchMatch]:
        return []

    monkeypatch.setattr(searches, "search_for_searches", nothing)

    content = await _call({"site_id": "plasmodb", "query": "predicted GPI anchor"})

    assert content == {"result": []}
