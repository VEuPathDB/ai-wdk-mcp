# Grab uv binary from the official image.
FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.14-slim

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# The lock names the client library by path, so the sibling is copied with the
# manifests. After publishing, the context is this folder and these three lines
# go with the path source.
COPY veupathdb-py/pyproject.toml veupathdb-py/
COPY veupathdb-py/README.md veupathdb-py/
COPY veupathdb-py/src veupathdb-py/src
COPY veupathdb-mcp/pyproject.toml veupathdb-mcp/
COPY veupathdb-mcp/uv.lock veupathdb-mcp/

WORKDIR /app/veupathdb-mcp
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_LINK_MODE=copy uv sync --frozen --no-install-project

WORKDIR /app
COPY veupathdb-mcp/README.md veupathdb-mcp/
COPY veupathdb-mcp/alembic.ini veupathdb-mcp/
COPY veupathdb-mcp/data veupathdb-mcp/data
COPY veupathdb-mcp/src veupathdb-mcp/src

ENV PYTHONPATH=/app/veupathdb-mcp/src
ENV PYTHONUNBUFFERED=1
WORKDIR /app/veupathdb-mcp

EXPOSE 8100

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8100/health || exit 1

CMD [".venv/bin/python", "-m", "veupathdb_mcp"]
