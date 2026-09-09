"""The veupathdb-research-mcp container: one uvicorn process serving the MCP endpoint.

The server holds no catalog and no database. It reaches the literature APIs and
the web search backend, and nothing else.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import IPv4Address

import uvicorn
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from veupathdb_mcp import __version__
from veupathdb_mcp.logging_setup import setup_logging
from veupathdb_mcp.research.metadata import (
    DEFAULT_MCP_PATH,
    guarded,
    protected_resource_routes,
)
from veupathdb_mcp.research.server import SERVER_NAME, build_server

HEALTH_PATH = "/health"
SERVE_PORT = 8110


class ServerHealth(BaseModel):
    """What a liveness probe reads off the server."""

    status: str
    server: str
    version: str


async def _health(request: Request) -> JSONResponse:
    """Liveness. The server preloads nothing, so serving is being ready."""
    del request
    health = ServerHealth(status="healthy", server=SERVER_NAME, version=__version__)
    return JSONResponse(health.model_dump())


def build_app() -> Starlette:
    """The served app: a public probe, the RFC 9728 document, and guarded MCP."""
    mcp_app = build_server().http_app(path=DEFAULT_MCP_PATH, stateless_http=True)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        del app
        setup_logging()
        async with mcp_app.lifespan(mcp_app):
            yield

    return Starlette(
        routes=[
            Route(HEALTH_PATH, _health, methods=["GET"]),
            *protected_resource_routes(),
            Mount("/", app=guarded(AuthContextMiddleware(mcp_app))),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    """Serve veupathdb-research-mcp on every interface of its container."""
    uvicorn.run(build_app(), host=str(IPv4Address(0)), port=SERVE_PORT)


if __name__ == "__main__":
    main()
