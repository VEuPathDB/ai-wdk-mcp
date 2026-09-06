# veupathdb-mcp

The VEuPathDB WDK catalog, parameter and gene tools, served over MCP as
`veupathdb-wdk-mcp`. Stateless: every tool names its site by value and acts as
the credential the transport gate verified. It is also a library - the tools
call the catalog, WDK and gene-lookup functions in process, and a host
application can call the same functions without going over the wire.

```bash
uv sync
uv run python -m veupathdb_mcp          # serves on :8100, /mcp and /health
```

## The seventeen tools

Catalog reads (service or user credential):

`list_record_types`, `search_for_searches`, `browse_search_categories`,
`list_searches`, `list_transforms`, `lookup_phyletic_codes`,
`search_example_plans`, `get_search_overview`, `get_parameter_options`.

Record, step and evidence reads (the VEuPathDB user whose bearer the call
carries):

`lookup_gene_records`, `resolve_gene_ids_to_records`,
`get_ai_expression_summary`, `get_step_estimated_size`,
`get_step_sample_records`, `get_step_download_url`,
`run_control_tests_on_search`, `enrich_gene_ids`.

The last two declare a call budget over the default in tool `_meta`
(`org.veupathdb.assistant/maxCallSeconds`), and `enrich_gene_ids` also declares
the stream part its result carries
(`org.veupathdb.assistant/streamPart`).

## Credential modes

| mode | what the caller sends | what it may reach |
| --- | --- | --- |
| `service` | a secret from `PATHFINDER_MCP_SERVICE_TOKENS`, as `app_id:secret` | the catalog reads, on the deployment's own WDK service token |
| `veupathdb_user` | a registered VEuPathDB bearer | every tool, acting as that user |

A guest bearer verifies as nothing: VEuPathDB refuses guest and anonymous
service calls, so the server mints no identity of its own. The bearer's
signature is checked against the OAuth server's published key
(`VEUPATHDB_OAUTH_URL`, default `https://auth.veupathdb.org`) and the verified
subject is cached for 300 seconds. **The server reads no application table and
keeps no account.**

`GET /.well-known/oauth-protected-resource` is the RFC 9728 document, served at
`PATHFINDER_MCP_BASE_URL`; without that variable the route refuses to build,
because a document naming the wrong host sends a client to the wrong authority.

## Settings

| variable | what it does |
| --- | --- |
| `DATABASE_URL` | the Postgres holding the two embedding tables |
| `OPENAI_API_KEY`, `EMBEDDING_*` | the embedder behind semantic search |
| `VEUPATHDB_SITES_CONFIG` | a `sites.yaml` of your own; unset reads the client library's bundled one |
| `VEUPATHDB_AUTH_TOKEN` | the deployment's service credential for user-independent reads |
| `VEUPATHDB_OAUTH_URL` | the OAuth server that signs VEuPathDB bearers |
| `PATHFINDER_MCP_BASE_URL` | the URL a client reads the RFC 9728 document at |
| `PATHFINDER_MCP_SERVICE_TOKENS` | `app_id:secret[,app_id:secret...]`; empty admits user bearers only |
| `SITE_CATALOG_BUDGET_MB` | accounted megabytes of catalogs and indexes one process holds (default 512) |
| `CATALOG_REFRESH_ENABLED` | whether this process rebuilds a stale catalog |
| `EMBEDDING_INDEX_SYNC_ENABLED` | whether this process writes vectors, or only searches what another wrote |

## The memory ceiling and the catalog snapshot

A cold site's catalog is built from WDK and is large: the container runs under a
**2 GB** ceiling, and a build inside a served call exceeds it. The deployment
that refreshes is a different process from the one that serves. Set
`CATALOG_REFRESH_ENABLED=false` and `EMBEDDING_INDEX_SYNC_ENABLED=false` on a
serving replica, and share `data/catalogs/` with the refreshing process as a
volume; the snapshots that ship in this folder seed it.

A snapshot carries `format_version` (`catalog/disk_cache.py`). A reader that
finds another version refuses the file and says so, rather than serving a
catalog it cannot read: two images that share the volume are two independently
versioned artefacts.

## What degrades when Postgres is unreachable

The catalog and the vector index are two stores. Loading a catalog reads WDK
and the snapshot on disk, so searches, parameters, record types and the site's
organism list are served whether or not Postgres answers. The index sync starts
beside that load and is never awaited by it: a store that refuses this process
is logged once with the driver's error class, and the catalog is served.

Everything the index answers then degrades to lexical ranking rather than
failing. `record_manager` opens every session through one boundary that turns a
driver refusal into `IndexStoreUnavailableError`, so a caller sees
`SemanticIndexUnavailableError` - the same type the embedding API raises
through `EmbeddingUnavailableError` - and never a bare `asyncpg` exception. Search
ranking, public-strategy ranking and study search each catch it and answer from
names and tokens.

## The two migration chains

This distribution owns `embedding_vectors` and `embedding_index_entries` and
carries its own alembic history under `src/veupathdb_mcp/alembic/`, recording
its position in `alembic_version_veupathdb_mcp`. A host application's chain uses
its own version table, so the two share a database without touching each other.

```bash
uv run python -m veupathdb_mcp.migrate     # bring the two tables to head
```

The server does **not** migrate at start: a replica that only reads must not
change a schema. A host that embeds this package as a library runs
`veupathdb_mcp.migrate.upgrade_head(connection)` on its own connection instead.
A database that already carries the two tables from a host's chain is stamped
once (`alembic stamp head` against this chain) rather than re-created.

## Admission

A tool server passes `mcp_conformance` before a deployment admits it, and this
one is read the same way:

```bash
pytest --pyargs mcp_conformance --mcp-endpoint http://localhost:8100/mcp --mcp-bearer "$TOKEN"
```

## Gates

```bash
uv sync --frozen
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest tests/unit                      # hermetic
uv run pytest tests/integration               # pgvector testcontainer
uv run pytest tests/live -m live_wdk --override-ini addopts=''   # one real site
```

`tests/unit/test_package_boundary.py` is the isolation proof: no module reaches
`pathfinder`, `assistant_core`, `pydantic_ai`, `langgraph` or `fastapi`, and
`uv sync --frozen` in this folder is what makes that an installation fact rather
than a lint rule.

The lock names `veupathdb-py` by the client repository
(`https://github.com/VEuPathDB/ai-veupathdb-client`) at one commit, so a checkout
of this repository alone installs and tests. To take a newer client: change `rev`
in `[tool.uv.sources]`, run `uv lock --upgrade-package veupathdb-py`, then
`uv sync`.

## Coverage, honestly

Many behaviours of this code are pinned by tests that span this package and its
host and stay there: the agent-side tool wrappers, the durable enrichment job,
and the deployment's served lane. This package's own suite is thinner than the
code's history suggests.
