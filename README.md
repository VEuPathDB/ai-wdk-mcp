# veupathdb-mcp

Two MCP servers, one distribution.

| server | module | port | what it serves |
| --- | --- | --- | --- |
| `veupathdb-wdk-mcp` | `veupathdb_mcp` | 8100 | the VEuPathDB WDK catalog, parameter, record and step tools |
| `veupathdb-research-mcp` | `veupathdb_mcp.research` | 8110 | literature search over seven APIs, and web search |

Both are stateless. A WDK tool names its site by value and acts as the
credential the transport gate verified; a research tool names no site and reads
the open web on the deployment's own account. This is also a library - the WDK
tools call the catalog, WDK and gene-lookup functions in process, and a host
application can call the same functions without going over the wire.

```bash
uv sync
uv run python -m veupathdb_mcp            # WDK, on :8100, /mcp and /health
uv run python -m veupathdb_mcp.research   # research, on :8110, /mcp and /health
```

## Why two servers in one distribution

Two processes, because the threat models differ: a server that reaches eight
open-web APIs is not the server that acts as a VEuPathDB user. Two servers also
keep the site guard unconditional, keep `veupathdb-wdk-mcp` a name that
describes what it serves, and give each server its own stream-part namespace.

One distribution, because a second repository would copy the settings scaffold,
the service-token parser, the logging setup, the Dockerfile, the CI workflow,
the lock and the release ceremony, and would add a second `veupathdb-py` pin to
keep in step. The price is one resolved environment: the research image
installs the database and embedding dependencies it never imports. The next
move, if that price grows, is optional dependency groups with the Dockerfile
targets syncing different extras.

The two servers share no setting: the WDK server reads `WDK_MCP_*` and
`VEUPATHDB_*`, the research server reads `RESEARCH_MCP_*`. A secret configured
for one admits nothing on the other.

## The seventeen WDK tools

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

## The two research tools

`web_search` and `literature_search`. Both are annotated
`readOnlyHint=True, openWorldHint=True` - open, because they reach servers
outside this deployment - and both declare the same stream part
(`data-research.sources`) and a 60 second call budget in tool `_meta`.

A result is a ranked index: the leading three rows carry 600 characters of
text and the rest carry 200, plus the url or the DOI that reaches the full
record again. `literature_search` reads Europe PMC, Crossref, OpenAlex,
Semantic Scholar, PubMed, arXiv, bioRxiv and medRxiv in parallel; one source
that fails is reported as that source's error and the rest still answer.

```bash
uv run python -m veupathdb_mcp.research
```

## Credential modes

| mode | what the caller sends | what it may reach |
| --- | --- | --- |
| `service` | a secret from `WDK_MCP_SERVICE_TOKENS`, as `app_id:secret` | the catalog reads, on the deployment's own WDK service token |
| `veupathdb_user` | a registered VEuPathDB bearer | every tool, acting as that user |

A guest bearer verifies as nothing: VEuPathDB refuses guest and anonymous
service calls, so the server mints no identity of its own. The bearer's
signature is checked against the OAuth server's published key
(`VEUPATHDB_OAUTH_URL`, default `https://auth.veupathdb.org`) and the verified
subject is cached for 300 seconds. **The server reads no application table and
keeps no account.**

`GET /.well-known/oauth-protected-resource` is the RFC 9728 document, served at
`WDK_MCP_BASE_URL`; without that variable the route refuses to build,
because a document naming the wrong host sends a client to the wrong authority.

## Settings

| variable | what it does |
| --- | --- |
| `DATABASE_URL` | the Postgres holding the two embedding tables |
| `OPENAI_API_KEY`, `EMBEDDING_*` | the embedder behind semantic search |
| `VEUPATHDB_SITES_CONFIG` | a `sites.yaml` of your own; unset reads the client library's bundled one |
| `VEUPATHDB_AUTH_TOKEN` | the deployment's service credential for user-independent reads |
| `VEUPATHDB_OAUTH_URL` | the OAuth server that signs VEuPathDB bearers |
| `WDK_MCP_BASE_URL` | the URL a client reads the RFC 9728 document at |
| `WDK_MCP_SERVICE_TOKENS` | `app_id:secret[,app_id:secret...]`; empty admits user bearers only |
| `SITE_CATALOG_BUDGET_MB` | accounted megabytes of catalogs and indexes one process holds (default 512) |
| `CATALOG_REFRESH_ENABLED` | whether this process rebuilds a stale catalog |
| `EMBEDDING_INDEX_SYNC_ENABLED` | whether this process writes vectors, or only searches what another wrote |

`PATHFINDER_MCP_BASE_URL` and `PATHFINDER_MCP_SERVICE_TOKENS` are read as the
old names of the first two for one release, and then removed.

### The research server

Its only credential mode is `service`. It reads no account, opens no database
and owns no table, so there is no `VEUPATHDB_OAUTH_URL` here: the deployment
that runs the server issues the secrets, and the RFC 9728 document names the
server itself as the authority.

| variable | what it does |
| --- | --- |
| `RESEARCH_MCP_BASE_URL` | the URL a client reads the RFC 9728 document at; without it the route refuses to build |
| `RESEARCH_MCP_SERVICE_TOKENS` | `app_id:secret[,app_id:secret...]`; empty admits nothing |
| `RESEARCH_MCP_TIMEOUT_SECONDS` | one outbound call's budget (default 15) |
| `RESEARCH_MCP_MAX_RETRIES` | how many times a client repeats a rate-limited call (default 3) |
| `RESEARCH_MCP_S2_API_KEY` | raises the Semantic Scholar rate limit for a keyed caller |
| `RESEARCH_MCP_CROSSREF_MAILTO` | a mailbox Crossref reads out of the User-Agent, which routes the call to its polite pool; empty keeps the anonymous pool |

## The names this server writes into a WDK account

A control run, an enrichment run, a gene-set step and a plan count each hold
their work in an internal WDK strategy under the caller's own account. The
host names them: `IntersectionConfig.internal_strategy_name`,
`EnrichmentService(strategy_name=...)`, `frozen_step_id(strategy_name=...)`
and `compute_plan_step_counts(strategy_name=...)`. The defaults name no
application (`"control test"`, `"enrichment analysis"`, `"gene set"`,
`"step counts"`).

A control run's cleanup matches the name the run wrote, so it takes the same
`IntersectionConfig` the run took:
`cleanup_internal_control_test_strategies(api, wdk_items, config)`. One object
carries the name for both, so a match cannot drift from a write. Two different
configs are two runs that do not see each other's leftovers.

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
pytest --pyargs mcp_conformance --mcp-endpoint http://localhost:8110/mcp --mcp-bearer "$RESEARCH_TOKEN"
```

The research lane runs in this repository's own CI, because the server needs no
site, no database and no VEuPathDB account. The WDK lane runs where a WDK
account exists.

## Gates

```bash
uv sync --frozen
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest tests/unit                      # hermetic
uv run pytest tests/integration               # pgvector testcontainer
uv run pytest tests/live -m live_wdk --override-ini addopts=''   # one real site
```

## Images

One `Dockerfile`, two targets. `--target research` builds the research server
on :8110; the default target builds the WDK server on :8100. Both install the
one lock, so the research image carries dependencies it never imports.

`tests/unit/test_package_boundary.py` is the isolation proof: no module reaches
`pathfinder`, `assistant_core`, `pydantic_ai`, `langgraph` or `fastapi`, and
`uv sync --frozen` in this folder is what makes that an installation fact rather
than a lint rule.

The lock names `veupathdb-py` by the client repository
(`https://github.com/VEuPathDB/ai-veupathdb-client`) at one release tag, so a
checkout of this repository alone installs and tests. To take a newer client:
change `tag` in `[tool.uv.sources]`, run `uv lock --upgrade-package veupathdb-py`,
then `uv sync`.

## Coverage, honestly

Many behaviours of this code are pinned by tests that span this package and its
host and stay there: the agent-side tool wrappers, the durable enrichment job,
and the deployment's served lane. This package's own suite is thinner than the
code's history suggests.
