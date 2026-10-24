"""The veupathdb-wdk-mcp container: one uvicorn process serving the MCP endpoint.

Every catalog and index a call loads stays in this process, under this
container's ceiling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import IPv4Address

import uvicorn
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from veupathdb.wdk import close_all_clients

from veupathdb_mcp import __version__
from veupathdb_mcp.embeddings import get_embedding_settings
from veupathdb_mcp.logging_setup import setup_logging
from veupathdb_mcp.metadata import (
    DEFAULT_MCP_PATH,
    guarded,
    protected_resource_routes,
)
from veupathdb_mcp.search_line import install_search_line
from veupathdb_mcp.server import SERVER_NAME, build_server
from veupathdb_mcp.settings import get_mcp_settings

HEALTH_PATH = "/health"
SERVE_PORT = 8100


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


def _search_line(database_url: str) -> AsyncEngine:
    settings = get_mcp_settings()
    return install_search_line(
        database_url,
        pool_size=settings.search_line_pool_size,
        max_overflow=settings.search_line_max_overflow,
        pool_timeout=settings.search_line_pool_timeout_seconds,
    )


def build_app() -> Starlette:
    """The served app: a public probe, the RFC 9728 document, and guarded MCP."""
    mcp_app = build_server().http_app(path=DEFAULT_MCP_PATH, stateless_http=True)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        del app
        setup_logging()
        database_url = get_embedding_settings().database_url
        line = _search_line(database_url) if database_url else None
        async with mcp_app.lifespan(mcp_app):
            yield
        await close_all_clients()
        if line is not None:
            await line.dispose()

    return Starlette(
        routes=[
            Route(HEALTH_PATH, _health, methods=["GET"]),
            *protected_resource_routes(),
            Mount("/", app=guarded(AuthContextMiddleware(mcp_app))),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    """Serve veupathdb-wdk-mcp on every interface of its container."""
    uvicorn.run(build_app(), host=str(IPv4Address(0)), port=SERVE_PORT)


if __name__ == "__main__":
    main()
