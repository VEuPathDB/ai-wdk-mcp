"""What veupathdb-wdk-mcp publishes about itself, and how it refuses an uncredentialed call."""

from __future__ import annotations

from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_protected_resource_routes,
)
from pydantic import AnyHttpUrl
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Route
from starlette.types import ASGIApp
from veupathdb.settings import get_veupathdb_settings

from veupathdb_mcp.auth import VEuPathDBTokenVerifier
from veupathdb_mcp.settings import get_mcp_settings

__all__ = [
    "DEFAULT_MCP_PATH",
    "RESOURCE_NAME",
    "guarded",
    "protected_resource_routes",
]

RESOURCE_NAME = "veupathdb-wdk-mcp"
DEFAULT_MCP_PATH = "/mcp"

_NO_BASE_URL = "WDK_MCP_BASE_URL must name the public URL of veupathdb-wdk-mcp."


def _resource_url(mcp_path: str) -> AnyHttpUrl:
    """The protected resource, which RFC 9728 requires to be the MCP endpoint."""
    base = get_mcp_settings().wdk_mcp_base_url.strip()
    if not base:
        raise ValueError(_NO_BASE_URL)
    return AnyHttpUrl(f"{base.rstrip('/')}/{mcp_path.lstrip('/')}")


def _resource_metadata_url(mcp_path: str) -> AnyHttpUrl:
    """Where the protected-resource document lives, per RFC 9728 section 3.1."""
    return build_resource_metadata_url(_resource_url(mcp_path))


def protected_resource_routes(mcp_path: str = DEFAULT_MCP_PATH) -> list[Route]:
    """The RFC 9728 document, naming the VEuPathDB OAuth server that signs tokens."""
    return create_protected_resource_routes(
        resource_url=_resource_url(mcp_path),
        authorization_servers=[
            AnyHttpUrl(get_veupathdb_settings().veupathdb_oauth_url)
        ],
        resource_name=RESOURCE_NAME,
    )


def guarded(app: ASGIApp, mcp_path: str = DEFAULT_MCP_PATH) -> ASGIApp:
    """Refuse a call carrying no verified credential, with the 401 challenge.

    The challenge names the protected-resource document, which is how a client
    discovers where to obtain a token.
    """
    return AuthenticationMiddleware(
        RequireAuthMiddleware(app, [], _resource_metadata_url(mcp_path)),
        backend=BearerAuthBackend(VEuPathDBTokenVerifier()),
    )
