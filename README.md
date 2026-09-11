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

## The names a host imports

Every package publishes a surface, so a host reads a name from the package rather
than from a file inside it.

| package | what it publishes |
| --- | --- |
| `veupathdb_mcp` | the version, the service-token registry, the tool error payload, the tool metadata keys |
| `veupathdb_mcp.catalog` | sites, record types, searches, parameter metadata and validation |
| `veupathdb_mcp.controls` | the control-test runners, their context and their result shapes |
| `veupathdb_mcp.embeddings` | the embedder, the two index tables, the record manager and the two indexes |
| `veupathdb_mcp.gene_lookup` | text lookup, id resolution and the organism list |
| `veupathdb_mcp.research` | the research server, its settings and its two tools |
| `veupathdb_mcp.tools` | the twenty-five served tools |
| `veupathdb_mcp.wdk` | step trees, step results, sizes, previews, expression, the vocabulary and defaults a form offers, and the AST a saved strategy converts into |
| `veupathdb_mcp.wdk.enrichment` | over-representation analysis, its result shapes and its parser |

`tests/unit/test_cold_import.py` holds the line: it imports every module of the
distribution first, on an interpreter that holds none of them, so an aggregating
`__init__` that closes a cycle fails there.

Two rules keep the surfaces acyclic. A control-test runner returns
`ControlTestResult`, a shape that lives beside it in `veupathdb_mcp.controls`,
and `veupathdb_mcp.tool_payloads` flattens that into `ControlOutcome` for a host
that renders one row. The vocabulary a WDK parameter offers and the defaults a
form states are `veupathdb_mcp.wdk.params`, read by the parent package rather
than by way of a subpackage. What a value looks like on the wire is not decided
here: `encode_param_value` asks the client's codec for the kind the parameter
declares, so this distribution and the client never disagree about one value.

The root package holds what both servers share, and nothing else: the research
process imports it and carries neither a WDK account, a WDK catalog nor a
database. Everything of the WDK side publishes its own surface instead, read by
module name:

| module | what it publishes |
| --- | --- |
| `veupathdb_mcp.auth` | the credential modes, the verified credential, the bearer verifier and the WDK identity |
| `veupathdb_mcp.metadata` | the resource name, the MCP path, the RFC 9728 routes and the transport gate |
| `veupathdb_mcp.migrate` | the version table, the tables this distribution owns, the autogenerate filter and the upgrade |
| `veupathdb_mcp.server` | the WDK server name, its tool list, its guards and its builder |
| `veupathdb_mcp.settings` | the WDK server's settings, the reader, and the source a host installs |
| `veupathdb_mcp.tool_payloads` | the flat control outcome, the download links, the catalog listings and the plan ranking |

`veupathdb_mcp.tool_meta` declares a surface too, and the root re-exports both
of its names.

`tests/unit/published_surface.json` is the checked-in copy of all sixteen
surfaces, so a name leaves one only by editing that file.

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

## The twenty-five WDK tools

Catalog reads (service or user credential):

`list_record_types`, `search_for_searches`, `browse_search_categories`,
`list_searches`, `list_transforms`, `lookup_phyletic_codes`,
`search_example_plans`, `get_search_overview`, `get_parameter_options`,
`get_search_param_specs`, `resolve_search_parameters`,
`validate_search_parameters`, `search_catalog_index`.

Record, step and evidence calls (the VEuPathDB user whose bearer the call
carries):

`lookup_gene_records`, `resolve_gene_ids_to_records`,
`get_ai_expression_summary`, `get_step_estimated_size`,
`get_step_sample_records`, `get_step_download_url`, `get_step_gene_ids`,
`run_control_tests_on_step`, `run_control_tests_on_search`, `count_plan_steps`,
`create_gene_set_step`, `enrich_gene_ids`.

Four of them declare a call budget over the default in tool `_meta`
(`org.veupathdb.assistant/maxCallSeconds`): the two control runs, the plan
count, and `enrich_gene_ids`, which also declares the stream part its result
carries (`org.veupathdb.assistant/streamPart`).

`count_plan_steps` and `create_gene_set_step` write into the calling user's
account, which is what their `readOnlyHint: false` states. Both hold their work
in an internal strategy, and the plan count deletes what it created.

A published call this list does not serve is an in-process import, and
`docs/knowledge/decisions/what-the-wire-serves-and-what-a-host-imports.md`
states the property that decides which is which.

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
| `EMBEDDING_SQL_ECHO` | whether the index's own engine echoes its statements |

Every setting answers to that one name. A host extends `McpSettings` and
`EmbeddingSettings` with its own model, so a field neither declares is the
host's alone and drives the host's own code.

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
and `compute_plan_step_counts(strategy_name=...)`. A wire caller names the last
two through the `strategy_name` argument of `create_gene_set_step` and
`count_plan_steps`. The defaults name no application (`"control test"`,
`"enrichment analysis"`, `"gene set"`, `"step counts"`).

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

`veupathdb_mcp.migrate` publishes `VERSION_TABLE` and `OWNED_TABLES`, so a host
that shares the database reads both names instead of retyping them, and its own
autogenerate filter stays true when this chain grows a table.

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

Both lanes run in this repository's own CI, on every push, at one conformance
pin. Neither needs a VEuPathDB account: the secret a lane sends is a service
token the deployment itself issues, and the suite calls a tool only with
arguments the runner supplies. A lane that supplies sample arguments, a second
identity and an account-state hook reads the same server more deeply, and that
lane belongs where a WDK account exists.

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
(`https://github.com/VEuPathDB/ai-veupathdb-client`) at one release tag, `v0.1.0a9`,
so a checkout of this repository alone installs and tests. To take a newer client:
change `tag` in `[tool.uv.sources]`, run `uv lock --upgrade-package veupathdb-py`,
then `uv sync`. Every name `src/` and `tests/` reads from the client comes from a client
package surface, never from a file inside one.

## Coverage, honestly

Many behaviours of this code are pinned by tests that span this package and its
host and stay there: the agent-side tool wrappers, the durable enrichment job,
and the deployment's served lane. This package's own suite is thinner than the
code's history suggests.
