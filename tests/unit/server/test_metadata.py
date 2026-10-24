"""What veupathdb-wdk-mcp publishes about itself, and how it refuses a call."""

from __future__ import annotations

from collections.abc import Iterator
from http import HTTPStatus

import httpx
import pytest
import structlog.testing
from mcp.shared.auth import ProtectedResourceMetadata
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send
from tests._support.bearers import jwt_shaped
from veupathdb.errors import ExternalServiceError
from veupathdb.wdk import VEuPathDBClaims

from veupathdb_mcp import identity
from veupathdb_mcp.auth import CredentialMode, McpCredential
from veupathdb_mcp.metadata import (
    RESOURCE_NAME,
    guarded,
    protected_resource_routes,
)

BASE_URL = "https://wdk-mcp.test"
MCP_PATH = "/mcp"
METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"
SERVICE_SECRET = "wdk-mcp-service-secret-0123456789ab"
REGISTERED = jwt_shaped("researcher@example.org")


@pytest.fixture
def mcp_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("WDK_MCP_BASE_URL", BASE_URL)
    monkeypatch.setenv("WDK_MCP_SERVICE_TOKENS", f"gene-page:{SERVICE_SECRET}")
    monkeypatch.setenv("VEUPATHDB_OAUTH_URL", "https://oauth.test")
    identity._subjects.clear()
    yield
    identity._subjects.clear()


async def _served_tool(scope: Scope, receive: Receive, send: Send) -> None:
    """Reports the mode of the credential the gate verified for this call."""
    credential: McpCredential = scope["user"].access_token
    await PlainTextResponse(f"served {credential.mode.value}")(scope, receive, send)


def _client() -> httpx.AsyncClient:
    app = Starlette(
        routes=[
            Route(MCP_PATH, endpoint=guarded(_served_tool), methods=["POST"]),
            *protected_resource_routes(),
        ]
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://wdk-mcp.test"
    )


async def test_the_metadata_document_carries_rfc_9728_required_fields(
    mcp_deployment: None,
) -> None:
    del mcp_deployment

    async with _client() as client:
        response = await client.get(METADATA_PATH)

    assert response.status_code == 200
    document = ProtectedResourceMetadata.model_validate_json(response.content)
    assert str(document.resource) == f"{BASE_URL}{MCP_PATH}"
    assert [str(server) for server in document.authorization_servers] == [
        "https://oauth.test/"
    ]
    assert document.bearer_methods_supported == ["header"]
    assert document.resource_name == RESOURCE_NAME


async def test_the_authorization_server_is_configurable(
    mcp_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_deployment
    monkeypatch.setenv("VEUPATHDB_OAUTH_URL", "https://auth.example.org")

    async with _client() as client:
        response = await client.get(METADATA_PATH)

    document = ProtectedResourceMetadata.model_validate_json(response.content)
    assert [str(server) for server in document.authorization_servers] == [
        "https://auth.example.org/"
    ]


async def test_a_call_without_a_credential_is_refused_with_the_challenge(
    mcp_deployment: None,
) -> None:
    del mcp_deployment

    async with _client() as client:
        response = await client.post(MCP_PATH, json={})

    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{BASE_URL}{METADATA_PATH}"' in challenge


async def test_a_rejected_credential_is_refused_with_the_challenge(
    mcp_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_deployment

    async def rejected(token: str, oauth_url: str) -> VEuPathDBClaims | None:
        del token, oauth_url
        return None

    monkeypatch.setattr(identity, "validate_oauth_token", rejected)

    async with _client() as client:
        response = await client.post(
            MCP_PATH, json={}, headers={"Authorization": "Bearer not-a-real-token"}
        )

    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert f'resource_metadata="{BASE_URL}{METADATA_PATH}"' in challenge
    assert "not-a-real-token" not in response.text
    assert "not-a-real-token" not in challenge


async def test_a_service_credential_reaches_the_call_as_the_application(
    mcp_deployment: None,
) -> None:
    del mcp_deployment

    async with _client() as client:
        response = await client.post(
            MCP_PATH, json={}, headers={"Authorization": f"Bearer {SERVICE_SECRET}"}
        )

    assert response.status_code == 200
    assert response.text == f"served {CredentialMode.SERVICE.value}"


async def test_a_registered_bearer_reaches_the_call_as_the_user(
    mcp_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_deployment

    async def registered(token: str, oauth_url: str) -> VEuPathDBClaims:
        del token, oauth_url
        return VEuPathDBClaims(sub="researcher@example.org", is_guest=False)

    monkeypatch.setattr(identity, "validate_oauth_token", registered)

    async with _client() as client:
        response = await client.post(
            MCP_PATH, json={}, headers={"Authorization": f"Bearer {REGISTERED}"}
        )

    assert response.status_code == 200
    assert response.text == f"served {CredentialMode.VEUPATHDB_USER.value}"


async def test_the_document_is_unreachable_without_a_public_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WDK_MCP_BASE_URL", "")

    with pytest.raises(ValueError, match="WDK_MCP_BASE_URL"):
        protected_resource_routes()


async def test_an_unreadable_identity_provider_is_refused_as_unavailable(
    mcp_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_deployment

    async def unreachable(token: str, oauth_url: str) -> VEuPathDBClaims | None:
        del token, oauth_url
        raise ExternalServiceError(
            service="VEuPathDB identity provider",
            detail=(
                "VEuPathDB identity provider at https://oauth.test/jwks "
                "cannot be read: All connection attempts failed"
            ),
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    monkeypatch.setattr(identity, "validate_oauth_token", unreachable)

    with structlog.testing.capture_logs() as logs:
        async with _client() as client:
            response = await client.post(
                MCP_PATH, json={}, headers={"Authorization": f"Bearer {REGISTERED}"}
            )

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["retry-after"] == "30"
    assert response.json() == {
        "type": "about:blank",
        "title": "Identity provider unavailable",
        "status": 503,
        "detail": "The VEuPathDB identity provider cannot be reached.",
    }
    assert [event for event in logs if event["log_level"] == "error"] == []


async def test_a_malformed_bearer_is_refused_with_the_challenge_while_the_provider_is_down(
    mcp_deployment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del mcp_deployment
    read: list[str] = []

    async def unreachable(token: str, oauth_url: str) -> VEuPathDBClaims | None:
        del oauth_url
        read.append(token)
        raise ExternalServiceError(
            service="VEuPathDB identity provider",
            detail="the identity provider cannot be read",
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    monkeypatch.setattr(identity, "validate_oauth_token", unreachable)

    async with _client() as client:
        response = await client.post(
            MCP_PATH, json={}, headers={"Authorization": "Bearer not-a-jwt"}
        )

    assert response.status_code == 401
    assert (
        f'resource_metadata="{BASE_URL}{METADATA_PATH}"'
        in (response.headers["www-authenticate"])
    )
    assert read == []
