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
| `veupathdb_mcp.audit` | the gene-model checks: genetic codes and translation, protein windows confirmed in DNA, a genome's gene rows, a named gene's record reads and proteins, a run's one gene-list upload and its reads of that list, each id's resolution or refusal, the site's organism records, a gene's model and its exon and CDS spans, at most two model reads a check adds per call, ortholog-group length statistics, the pseudogene-call, selenoprotein-end, protein-length, split, gene-fusion, strain-model, missing-gene, organelle-join and RNA-seq intron-support checks, the anatomy of a pseudogene call, a genome's pseudogene calls paired with a reference genome and a rate with its Wilson interval, floor and ceiling, the genome priority from the served BUSCO scores, the evidence a gene record serves and a genome's provenance, and the inputs their served tools read |
| `veupathdb_mcp.catalog` | sites, record types, searches, parameter metadata and validation, the shortlist a long vocabulary is shown as, other sites' experiment cards, the OrthoMCL phyletic expression written from a typed pattern (`write_phyletic_expression`), and whether a site lists the gene record type (`require_gene_records`) |
| `veupathdb_mcp.controls` | the control-test runners, their context and their result shapes |
| `veupathdb_mcp.embeddings` | the embedder, its three tables, the record manager and the indexes on them |
| `veupathdb_mcp.gene_lookup` | text lookup, id resolution (each id answered on its own by `read_each_gene_id`) and the organism list |
| `veupathdb_mcp.research` | the research server, its settings and its two tools |
| `veupathdb_mcp.separation` | the separation run, its request, its progress rows, its result, the request charges it makes and the hypergeometric tail it reads controls by |
| `veupathdb_mcp.testing` | the recordings this distribution ships for a host's suite: the OrthoMCL count recordings (`ORTHOMCL_COUNTS`) |
| `veupathdb_mcp.tools` | the forty-four served tools |
| `veupathdb_mcp.wdk` | step trees, sizes, the sample of a built step (`step_sample_records`), a step's gene ids read up to a limit the caller names (`StepTooLargeError` past it), a step's columns (`list_step_columns`) and its records counted by one column (`count_by_column`, `ColumnNotCountedError` for a column that cannot be counted), an OrthoMCL group's proteins per genome (`group_genome_counts`, from its `TaxonCounts` table), downloads, expression, the vocabulary and defaults a form offers, and the AST a saved strategy converts into |
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
| `veupathdb_mcp.auth` | the credential modes, the verified credential, the bearer verifier, the refusal an unreachable identity provider earns and the WDK identity |
| `veupathdb_mcp.metadata` | the resource name, the MCP path, the RFC 9728 routes and the transport gate |
| `veupathdb_mcp.migrate` | the version table, the tables this distribution owns, the autogenerate filter and the upgrade |
| `veupathdb_mcp.server` | the WDK server name, its tool list, its guards and its builder |
| `veupathdb_mcp.settings` | the WDK server's settings, the reader, and the source a host installs |
| `veupathdb_mcp.tool_payloads` | the flat control outcome, the download links, the catalog listings and the plan ranking |

`veupathdb_mcp.tool_meta` declares a surface too, and the root re-exports both
of its names.

`tests/unit/published_surface.json` is the checked-in copy of all twenty
surfaces, so a name leaves one only by editing that file.

## Why two servers in one distribution

Two processes, because the threat models differ: a server that reaches eight
open-web APIs is not the server that acts as a VEuPathDB user. Two servers also
keep the site guard unconditional, keep `veupathdb-wdk-mcp` a name that
describes what it serves, and give each server its own stream-part namespace.

One distribution, because a second repository would copy the settings scaffold,
the service-token parser, the logging setup, the CI workflow, the lock and the
release ceremony, and would add a second `veupathdb-py` pin to keep in step. The
price is one resolved environment: the research image installs the database and
embedding dependencies it never imports. The next move, if that price grows, is
optional dependency groups with each Dockerfile syncing its own extras.

The two servers share no setting: the WDK server reads `WDK_MCP_*` and
`VEUPATHDB_*`, the research server reads `RESEARCH_MCP_*`. A secret configured
for one admits nothing on the other.

## The forty-four WDK tools

Catalog reads (service or user credential):

`list_record_types`, `search_for_searches`, `browse_search_categories`,
`list_searches`, `list_transforms`, `lookup_phyletic_codes`,
`build_phyletic_expression`, `search_example_plans`, `get_search_overview`, `get_parameter_options`,
`get_search_param_specs`, `resolve_search_parameters`,
`validate_search_parameters`, `search_catalog_index`,
`rank_experiments_elsewhere`, `read_experiment`.

Record, step and evidence calls (the VEuPathDB user whose bearer the call
carries):

`lookup_gene_records`, `resolve_gene_ids_to_records`,
`get_ai_expression_summary`, `get_step_estimated_size`,
`get_step_sample_records`, `get_step_download_url`, `get_step_gene_ids`,
`get_step_columns`, `count_step_by_column`,
`run_control_tests_on_step`, `run_control_tests_on_search`, `count_plan_steps`,
`create_gene_set_step`, `enrich_gene_ids`.

Gene-model checks (the VEuPathDB user whose bearer the call carries):

`audit_pseudogene_call`, `audit_selenoprotein_end`, `audit_gene_length`,
`audit_gene_split`, `audit_strain_model`, `audit_missing_gene`,
`audit_organelle_gene`, `audit_genome_priority`, `audit_pseudogene_anatomy`,
`audit_genome_pseudogene_calls`, `audit_gene_evidence`, `audit_genome_provenance`,
`audit_intron_support`, `audit_gene_fusion`.

Every check that takes gene ids resolves each id through the site (the gene record the
id reads, its own id, an alias or a previous id; else the one gene whose own id,
without its `:` qualifier, or whose transcript id the site's text search finds) and
answers `geneIds`, each id given beside the gene id it resolved to. A named gene, its
protein and its ortholog group are record reads, so these checks upload no gene list;
a host reads a run's list with `read_gene_list`, one gene record per id, which uploads
nothing either.

Eighteen of them declare a call budget over the default in tool `_meta`
(`org.veupathdb.assistant/maxCallSeconds`): the two control runs, the plan
count, the phyletic expression builder, the eleven gene-model checks that read DNA
or whole-genome gene reports, the two gene lookups, which read one gene record per
id, and `enrich_gene_ids`, which also declares the
stream part its result carries (`org.veupathdb.assistant/streamPart`).
`audit_genome_priority`,
`audit_gene_evidence` and `audit_genome_provenance` read no DNA (one organism
report, or the gene record type and one gene record) and keep the default.

`count_plan_steps`, `create_gene_set_step`, `enrich_gene_ids`,
`run_control_tests_on_search` and `run_control_tests_on_step` write into the calling
user's account, which is what their `readOnlyHint: false` states. Each holds its work
in an internal strategy. The plan count deletes what it created. Both control runs
delete every step and strategy they created, also when the run fails or is
cancelled; the step run first copies the tested step out of its strategy.
`create_gene_set_step`, `enrich_gene_ids` and both control runs each write one
id-list dataset, and their descriptions say so. WDK offers no delete for a dataset, so
the dataset stays. `lookup_gene_records` and `resolve_gene_ids_to_records` read each
named gene by its own gene record and write nothing.

A published call this list does not serve is an in-process import, and
`docs/knowledge/decisions/what-the-wire-serves-and-what-a-host-imports.md`
states the property that decides which is which.

`lookup_phyletic_codes` gives each match its code, its label, `leaf` and
`genomes`, the number of genomes under it, and groups the genomes the query names
by species under `species`. On OrthoMCL it reads the site's taxonomy, and the
`phyletic_expression` help states the counting, absence and precedence rules the
site was measured to follow.

`build_phyletic_expression` writes OrthoMCL's `phyletic_expression` from a typed
pattern: a count over a set (`codes`, `all_except`, `each_species_of`,
`each_genome_of`) by genomes, proteins or a share of genomes; a comparison of the
proteins of two sets read per genome, as totals or as per-genome averages; and
`all_of`, `any_of` and `none_of` over them, nested. A genome with no protein counts 0.
It multiplies nesting out into the OR of AND terms the site reads, writes each set as
the fewest taxonomy codes that cover it, refuses a pattern that holds for every group
or for none, checks the expression with the client's `check_expression`, and counts
it with one count report. A comparison first reads, by bisection over count reports
sent one after another, the largest count of its right side in any group, and writes
one band per count. A pattern whose expression would pass 2,000 OR terms, 150,000
characters, or 160,000,000 for its OR terms times its characters (the most one search
was measured to run within the client's 30 second read timeout), or whose count is
predicted past the 300 second budget, is refused before its count with its terms
and characters, as a limit of this library; a site refusal is returned as the site
wrote it. A long expression's reading is an outline of the pattern, at most 2,000
characters.

A search the site publishes no description for may carry a measured note in its
place (`catalog/search_notes.py`); a note never replaces a description the site
publishes. OrthoMCL's `GroupsBySingleCopy` carries the only one: it selects
groups by how many genomes hold a protein and does not limit the proteins of one
genome, and one protein in every genome of a list is a `GroupsByPhyleticPattern`
expression.

`count_step_by_column` counts any built step, a transform step among them, by one
column with the site's `byValue` column reporter. It reads the step, its record type
and its search first, and refuses a column that is not one of the step's, or that is
not STRING or NUMBER with `byValue` in its `tools.reports`, naming the columns that can
be counted, before any report. A string column answers its values ranked by count, at
most `top` (1 to 200, 20 by default), with the number of distinct values; a number
column answers the site's bins and its minimum, maximum and mean. A refused report is
a tool error, never an empty count. `get_step_columns` lists the columns, the
record type's attributes and the search's own, with their data type and whether they
can be counted, and `transforms`: each search of the site's catalog that takes the
step's record type as its one input and produces another record type (a search with
a second input, a combine among them, and a search back into the same record type are
left out), the record type it produces and the columns of that record type
and of the transform's own search that can be counted. Neither creates a step or a
dataset.

`get_step_gene_ids` answers at most 200 gene ids. It asks the site for one record
more, refuses a larger step by its id and the limit, and names
`get_step_download_url`, which reads the whole step.

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
| `service` | a secret from `WDK_MCP_SERVICE_TOKENS`, as `app_id:secret` | the paths VEuPathDB opens to a guest, as the one shared guest token; a tool that needs a registered user is refused as login required |
| `veupathdb_user` | a registered VEuPathDB bearer | every tool, acting as that user |

A guest bearer verifies as nothing: most VEuPathDB paths serve registered users
only, so the server mints no identity of its own for a caller. The server holds
no VEuPathDB account: a call with no user bearer reads the open paths as the
client library's shared guest token, and a gene lookup or any other keyed read
needs a user bearer. The bearer's
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
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | the same address in parts, in place of `DATABASE_URL`; setting `POSTGRES_PASSWORD` and `DATABASE_URL` together fails startup |
| `OPENAI_API_KEY` | the key the Decisions API and the OpenAI embedder are called on; required, and startup fails without one |
| `EMBEDDING_*` | the embedder behind semantic search |
| `VEUPATHDB_SITES_CONFIG` | the `sites.yaml` this deployment serves; required, because the client library ships no default list and the first site read fails without one |
| `VEUPATHDB_OAUTH_URL` | the OAuth server that signs VEuPathDB bearers |
| `WDK_MCP_BASE_URL` | the URL a client reads the RFC 9728 document at |
| `WDK_MCP_SERVICE_TOKENS` | `app_id:secret[,app_id:secret...]`; empty admits user bearers only |
| `SITE_CATALOG_BUDGET_MB` | accounted megabytes of catalogs and indexes one process holds (default 512) |
| `CATALOG_REFRESH_ENABLED` | whether this process rebuilds a stale catalog |
| `EMBEDDING_INDEX_SYNC_ENABLED` | whether this process writes vectors, or only searches what another wrote |
| `EMBEDDING_SQL_ECHO` | whether the index's own engine echoes its statements |
| `EMBEDDING_DB_POOL_SIZE`, `EMBEDDING_DB_MAX_OVERFLOW` | the connections the index's own engine keeps, and the ones it opens past them (defaults 2 and 6) |
| `EMBEDDING_DB_POOL_TIMEOUT_SECONDS` | how long the index's own engine waits for a connection before it fails (default 30) |
| `SEARCH_LINE_POOL_SIZE`, `SEARCH_LINE_MAX_OVERFLOW` | the connections the expensive-search line keeps, and the ones it opens past them (defaults 1 and 1); each search holds one for its whole run |
| `SEARCH_LINE_POOL_TIMEOUT_SECONDS` | how long a search waits for a line connection; empty waits without a limit, as the line does (the default) |
| `STRATEGY_LINE_POOL_SIZE`, `STRATEGY_LINE_MAX_OVERFLOW` | the connections the strategy line keeps, and the ones it opens past them (defaults 2 and 2), apart from the index pool; each request on a strategy holds one for that request |
| `STRATEGY_LINE_POOL_TIMEOUT_SECONDS` | how long a strategy request waits for a line connection; empty waits without a limit (the default) |
| `DECISIONS_TIMEOUT_SECONDS` | how long one Decisions request from `search_for_searches` or a narrowed `get_parameter_options` may take before the read keeps its own result (default 15) |
| `DECISIONS_VOCAB_MIN_CONFIDENCE` | the confidence at or above which a vocabulary pick is settled (default 0.5) |

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
`counted_id_list(strategy_name=...)` checks an id list on a step under an internal
strategy too, and deletes that strategy before it returns; the dataset stays.

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

This distribution owns `embedding_vectors`, `embedding_index_entries` and
`experiment_cards`, and carries its own alembic history under
`src/veupathdb_mcp/alembic/`, recording its position in
`alembic_version_veupathdb_mcp`. A host application's chain uses
its own version table, so the two share a database without touching each other.

```bash
uv run python -m veupathdb_mcp.migrate     # bring the owned tables to head
```

`veupathdb_mcp.migrate` publishes `VERSION_TABLE` and `OWNED_TABLES`, so a host
that shares the database reads both names instead of retyping them, and its own
autogenerate filter stays true when this chain grows a table.

The server does **not** migrate at start: a replica that only reads must not
change a schema. A host that embeds this package as a library runs
`veupathdb_mcp.migrate.upgrade_head(connection)` on its own connection instead.
A database that already carries the two index tables from a host's chain is stamped
once at their revision (`alembic stamp 2026_08_29_0001` against this chain) and then
upgraded, rather than re-created.

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
uv run pytest tests/live -m live_wdk --override-ini addopts=''   # one QA site
node scripts/check-knowledge.mjs && node --test scripts/check-knowledge.test.mjs
node scripts/check-test-sites.mjs && node --test scripts/check-test-sites.test.mjs
```

Every test, the live lane included, reads the QA site list the client library ships
(`veupathdb.testing.QA_SITES_FILE`), and `scripts/record_all_datasets.py` records from
it whatever the environment names. `check-test-sites.mjs` fails on a production or beta
host anywhere outside `README.md`, `docs/` and the catalog cache under `data/catalogs/`.
Every recording is made on QA. A test whose recording is absent is skipped with
`veupathdb.testing.NEEDS_QA_RECORDING` while `veupathdb.testing.needs_qa_recording`
finds it absent, so a recording lifts the skip with no change to the test
([the decision](docs/knowledge/decisions/tests-run-against-qa-and-a-deployment-names-its-sites.md)).

## Images

Two Dockerfiles, one image each. A file builds its server as its last stage, so
neither build takes a target:

```bash
docker build -t wdk-mcp .                                # the WDK server, on :8100
docker build -f Dockerfile.research -t research-mcp .    # the research server, on :8110
```

Every stage before the last one is the same in both files, so both images install
the one lock and the research image carries dependencies it never imports.
`tests/unit/test_dockerfiles.py` fails when the two install stages differ, when the
last stage of a file does not build on the install stage, or when it serves another
module.

`Jenkinsfile` publishes both to Docker Hub, the WDK server as
`veupathdb/pathfinder-wdk-mcp` and the research server as
`veupathdb/pathfinder-research-mcp`. A push to `main` publishes `latest`. A release
tag publishes its version, and the builder reads a tag only in its semver spelling:
`v`, then the version with a hyphen before a pre-release. Version `0.2.0b5` is tagged
`v0.2.0-b5` and publishes `0.2.0-b5`; version `0.2.0` is tagged `v0.2.0` and
publishes `0.2.0`, `0.2` and `0`. A tag in the PEP 440 spelling (`v0.2.0b5`)
publishes no image. `__version__` keeps its PEP 440 spelling, because PEP 440 reads
`0.2.0-b5` as `0.2.0b5`, and a host that pins this repository by tag names the semver
tag.

`tests/unit/test_package_boundary.py` is the isolation proof: no module reaches
`pathfinder`, `assistant_core`, `pydantic_ai`, `langgraph` or `fastapi`, and
`uv sync --frozen` in this folder is what makes that an installation fact rather
than a lint rule.

The lock names `veupathdb-py` by the client repository
(`https://github.com/VEuPathDB/ai-veupathdb-client`) at one release tag, `v0.1.0b24`,
so a checkout of this repository alone installs and tests. To take a newer client:
change `tag` in `[tool.uv.sources]`, run `uv lock --upgrade-package veupathdb-py`,
then `uv sync`. Every name `src/` and `tests/` reads from the client comes from a client
package surface, never from a file inside one.

## Coverage, honestly

Many behaviours of this code are pinned by tests that span this package and its
host and stay there: the agent-side tool wrappers, the durable enrichment job,
and the deployment's served lane. This package's own suite is thinner than the
code's history suggests.
