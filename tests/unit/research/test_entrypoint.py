"""The ASGI app the veupathdb-research-mcp container serves."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp.shared.auth import ProtectedResourceMetadata
from mcp.types import CallToolResult, JSONRPCResponse, ListToolsResult, TextContent
from starlette.applications import Starlette

from veupathdb_mcp import __version__
from veupathdb_mcp.research.__main__ import HEALTH_PATH, ServerHealth, build_app
from veupathdb_mcp.research.metadata import DEFAULT_MCP_PATH
from veupathdb_mcp.research.server import SERVER_NAME, TOOLS, build_server

BASE_URL = "https://research-mcp.veupathdb.org"
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
SERVICE_SECRET = "research-mcp-service-secret-0123456789ab"


@pytest.fixture
def research_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("RESEARCH_MCP_BASE_URL", BASE_URL)
    monkeypatch.setenv("RESEARCH_MCP_SERVICE_TOKENS", f"pathfinder:{SERVICE_SECRET}")
    return


@asynccontextmanager
async def _serving() -> AsyncIterator[httpx.AsyncClient]:
    """The container's app, with the lifespan uvicorn would have run."""
    app: Starlette = build_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://research-mcp.test",
        ) as client,
    ):
        yield client


async def _rpc(
    client: httpx.AsyncClient,
    method: str,
    params: dict[str, object] | None = None,
    token: str | None = None,
) -> httpx.Response:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return await client.post(
        DEFAULT_MCP_PATH,
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def _rpc_result(response: httpx.Response) -> object:
    """The JSON-RPC result carried by the response's single SSE frame."""
    frame = next(
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    )
    return JSONRPCResponse.model_validate_json(frame).result


def _error_text(result: CallToolResult) -> str:
    return " ".join(
        block.text for block in result.content if isinstance(block, TextContent)
    )


async def test_the_health_route_answers_a_probe_without_a_credential(
    research_deployment: None,
) -> None:
    del research_deployment

    async with _serving() as client:
        response = await client.get(HEALTH_PATH)

    assert response.status_code == 200
    health = ServerHealth.model_validate_json(response.content)
    assert (health.status, health.server) == ("healthy", SERVER_NAME)


async def test_the_protected_resource_document_is_served_without_a_credential(
    research_deployment: None,
) -> None:
    del research_deployment

    async with _serving() as client:
        response = await client.get(METADATA_PATH)

    assert response.status_code == 200
    document = ProtectedResourceMetadata.model_validate_json(response.content)
    assert str(document.resource) == f"{BASE_URL}{DEFAULT_MCP_PATH}"


async def test_an_uncredentialed_tools_list_is_refused_with_the_challenge(
    research_deployment: None,
) -> None:
    del research_deployment

    async with _serving() as client:
        response = await _rpc(client, "tools/list")

    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert f'resource_metadata="{BASE_URL}{METADATA_PATH}"' in challenge


async def test_a_bearer_no_application_holds_is_refused(
    research_deployment: None,
) -> None:
    """No VEuPathDB user reaches this server, so an unknown secret is nothing."""
    del research_deployment

    async with _serving() as client:
        response = await _rpc(client, "tools/list", token="not-a-configured-secret")

    assert response.status_code == 401


async def test_a_credentialed_tools_list_serves_the_published_inventory(
    research_deployment: None,
) -> None:
    del research_deployment

    async with _serving() as client:
        response = await _rpc(client, "tools/list", token=SERVICE_SECRET)

    assert response.status_code == 200
    listing = ListToolsResult.model_validate(_rpc_result(response))
    assert sorted(tool.name for tool in listing.tools) == sorted(
        row.fn.__name__ for row in TOOLS
    )


async def test_a_bad_argument_answers_with_a_tool_error_naming_the_field(
    research_deployment: None,
) -> None:
    """The conformance error family reads the field name out of the message."""
    del research_deployment

    async with _serving() as client:
        response = await _rpc(
            client,
            "tools/call",
            {
                "name": "web_search",
                "arguments": {"query": {"refused": "by the schema"}},
            },
            token=SERVICE_SECRET,
        )

    assert response.status_code == 200
    result = CallToolResult.model_validate(_rpc_result(response))
    assert result.isError is True
    assert "query" in _error_text(result)


async def test_the_server_declares_the_deployments_version() -> None:
    assert build_server().version == __version__
