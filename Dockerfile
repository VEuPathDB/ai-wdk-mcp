# Grab uv binary from the official image.
FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.14-slim

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

COPY README.md alembic.ini ./
COPY data data
COPY src src

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV CATALOG_CACHE_DIR=/app/data/catalogs

EXPOSE 8100

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8100/health || exit 1

CMD [".venv/bin/python", "-m", "veupathdb_mcp"]
