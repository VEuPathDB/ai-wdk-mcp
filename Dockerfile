# Grab uv binary from the official image.
FROM ghcr.io/astral-sh/uv:0.12.10 AS uv

# One distribution, two served images. Build the research server with
# `--target research`; the default target is the WDK server.
FROM python:3.14-slim AS base

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

# The lock names the client library by a git URL, so the build stage needs git.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    UV_LINK_MODE=copy uv sync --frozen --no-install-project

COPY README.md ./
COPY src src

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

FROM base AS research

EXPOSE 8110

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8110/health || exit 1

CMD [".venv/bin/python", "-m", "veupathdb_mcp.research"]

FROM base AS wdk

COPY alembic.ini ./
COPY data data

ENV CATALOG_CACHE_DIR=/app/data/catalogs

EXPOSE 8100

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8100/health || exit 1

CMD [".venv/bin/python", "-m", "veupathdb_mcp"]
