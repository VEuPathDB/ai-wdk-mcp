# Knowledge log

## 2026-09-22

- `veupathdb-mcp` is 0.2.0a19: it pins `veupathdb-py` v0.1.0a11, whose search-config update
  carries the step's own input-step values, so a transform's own parameter can be changed.
- `veupathdb-mcp` is 0.2.0a20: it pins `veupathdb-py` v0.1.0a12, one step read per search-config
  update.

## 2026-09-16

- `veupathdb-mcp` is 0.2.0a18. A step the site will not run reports words, not the bundle.
  `veupathdb_mcp.wdk.describe_step_refusal` reads the validation bundle WDK renders inside its
  own prose, follows the answer parameter into the bundle of each input step it names, and
  reports the parameter and the value the site refuses. The three bundle fields
  (`keyedErrors`, `validationLevel`, `validationStatus`) are required, so a JSON object of
  another shape is not read as a bundle and the caller keeps its own text; a bundle whose leaf
  message the reader does not know reports one short sentence instead of the blob. The reader
  names no user, no step id and no JSON, and the caller keeps logging the whole refusal.
  Measured on the refusal a saved two-step strategy got: two nested bundles and four
  identifiers became "This strategy cannot run. The second input of the step you ran sets
  'profileset_generic' to 'P. falciparum Su Strand Specific RNA Seq data - - Sense', which the
  site no longer offers. Open that step and choose a value the site offers now." Enrichment is
  the first caller.

- `veupathdb-mcp` is 0.2.0a17. A gene set taken from a single-step strategy carries that
  search's typed parameters. `_extract_step_search_context` reads the step's own search
  document and decodes its wire values through the seam the strategy snapshot already used,
  which is now `veupathdb_mcp.wdk.param_decoding`: one way to get a search's parameter kinds,
  two callers. Parameters are None when the search document cannot be read and an empty
  mapping when the step sets none of the parameters the search declares, so a caller tells the
  two apart. A step whose document is unreadable still reports its genes and its search name.
  Measured against the recorded `search_genes_by_molecular_weight` document: a step wired with
  `min_molecular_weight=50000`, `max_molecular_weight=50100` and `organism=["Plasmodium
  falciparum 3D7"]` reported no parameters and now reports those three as typed values.

- `veupathdb-mcp` is 0.2.0a17. A count reports no number only when the service answered about
  the one search it asked for. `count_search_answer` reads the refusal's own code, and for a WDK
  refusal its HTTP status: any 4xx is such an answer and leaves that count unknown, while a site
  the deployment does not serve, a caller with no registered token, another service, and any 5xx
  reach the caller, because a null from those says "no records here" where nothing answered at
  all. `compute_plan_step_counts` still reports None for a step whose own count cannot be read.
  Measured both ways: a count that absorbed every refusal answered "this step has no readable
  count" for a site that does not exist, and a host that had refused such a request served 200
  with nulls; and the anonymous report endpoint answers 401 with a request for an API key on
  some searches, so a 401 is the endpoint describing itself and not the caller's standing.

- `veupathdb-mcp` is 0.2.0a16. `count_search_answer` is published from
  `veupathdb_mcp.wdk`: one search counted through the anonymous report endpoint with
  `numRecords: 0`, which creates no step, no strategy and needs no user session. It is the
  count `compute_plan_step_counts` already made for a leaf-only plan, now named and reachable
  by a host, so a host that counts one binding does not carry its own copy. `timeout_seconds`
  bounds one read and reports no count when it expires; the default waits as long as the
  client does, which is what the plan counts pass. An answer that publishes no total now
  reports no count instead of raising, so one unreadable leaf no longer ends a whole plan
  count.

## 2026-09-15

- `veupathdb-mcp` is 0.2.0a15. A search backend that answers 200 with a body its format does
  not hold is one refused attempt, not a dead search: the metasearch and the keyed engine
  both record the attempt and the next engine is asked. A literature API that answers a body
  that is not JSON names itself and is asked once, in place of a raw decode error after three
  attempts.

- `veupathdb-mcp` is 0.2.0a14. `RESEARCH_MCP_SEARXNG_URL` names a SearXNG instance the web
  tool asks first, before a keyed engine and the scraped ones; see
  [A metasearch the deployment runs answers first](decisions/a-metasearch-the-deployment-runs-answers-first.md).
  Startpage joins the scraped engines.

- `veupathdb-mcp` is 0.2.0a13. A web engine that answers and finds nothing has answered:
  a query no engine finds a page for returns an empty result with guidance, and the
  tool raises only when every engine was blocked. Measured: three empty searches in one
  turn were three served errors, and a host that retries a tool three times ended the
  turn with no reply.

- `veupathdb-mcp` is 0.2.0a12. A `10.3410/` DOI (H1 Connect, once Faculty Opinions) is a
  recommendation of a paper and ranks as no article; a query with no letter or digit is
  refused as no query by both search tools.

- `veupathdb-mcp` is 0.2.0a11. An abstract that is the venue name or the title describes
  nothing, so encyclopedia and dictionary entries no longer lead a literature answer.

- `veupathdb-mcp` is 0.2.0a10. With `RESEARCH_MCP_BRAVE_SEARCH_API_KEY` set, the web tool
  asks the Brave Search API before any scraped engine and the served answer carries what
  the call cost (`costUsd`); see
  [A keyed engine answers first and prices the call](decisions/a-keyed-engine-answers-first-and-prices-the-call.md).

- `veupathdb-mcp` is 0.2.0a9. A literature record with an identifier and no abstract that
  describes it ranks below one that has both, so a one-page venue item whose title repeats
  the query no longer leads; see
  [A listing page never outranks a paper](decisions/a-listing-page-never-outranks-a-paper.md).
  When Europe PMC and PubMed both return nothing while other sources answer, the guidance
  says so and asks for a shorter query.

- `veupathdb-mcp` is 0.2.0a8. Literature relevance ranks a paper above a page: a listing
  page, a search page and a DOI prefix that registers no journal article rank below every
  article, and the score decides inside a band. Both search tools now report what they
  searched: one row per literature source with its count and its error, and, for the web,
  the engine that answered and every engine that refused.

## 2026-09-11

- The client pin is `v0.1.0a10`, the release that publishes the signing-key reset, so
  a host that pins both distributions resolves one client URL. `veupathdb-mcp` is 0.2.0a7.

- This bundle exists from this version on. Before it, the rules that bind these two
  servers to a host - which of their functions a host calls in process, which settings
  sources it installs, which alembic chain it runs, and who owns the embedder drift
  gate - were recorded in another repository or in none. The backlog it opens with is
  the set of couplings and downward re-derivations that a host other than the first one
  would hit.

- Eight capabilities that had no tool row have one, so the served inventory is 25 tools
  rather than 17: parameter binding, parameter validation, parameter specs, semantic
  catalog search, plan step counts, control tests on a step, a materialized gene-set
  step, and a step's gene ids. Each carries the contract of the published call it
  wraps, and [what the wire serves](decisions/what-the-wire-serves-and-what-a-host-imports.md)
  states the property that decides the rest. A step's gene ids answer bounded: a step
  that holds more genes than one call carries is refused by name, and the download url
  reads the whole set.

- A materialized gene-set step is remembered per account, not per site and membership,
  so no caller is handed a step id that names a step in somebody else's WDK account. The
  account is the request's own WDK token, because
  [that is what decides where the step lands](decisions/a-frozen-step-is-keyed-by-the-account-it-lands-in.md).
  A call that carries no token is refused rather than cached as anybody.

- The WDK server proves admission in this repository's CI, beside the research server
  and at one conformance pin. A service secret is issued by the deployment that serves,
  so neither lane needs a VEuPathDB account, a site or a database.

- A step read asks for gene attributes only when the caller names a gene record type.
  `gene_sample_attributes` takes `record_type: str`, and no record type stands in for
  another. A host that passed nothing passes its own default at the call site.

- Each setting answers to one name, and that name states no application. The two
  `PATHFINDER_MCP_` alias choices are gone from `McpSettings`, and the index settings
  name the index: `api_debug` is `embedding_sql_echo`, so a host's own SQL echo drives
  the host's engine alone. No checkout produced either old name, so the only variable a
  deployment adds is `EMBEDDING_SQL_ECHO`, in its own compose file and its own
  environment sample, and only when it wants the index to echo.

- The root package re-exports the three leaf modules both servers share. The WDK
  credential path, its settings and its published metadata declare their own surfaces,
  read by module name, because
  [importing any module runs the package `__init__`](decisions/the-root-package-holds-what-both-servers-share.md).

- The conversion from a saved WDK strategy to a strategy AST is
  `veupathdb_mcp.wdk.strategy_snapshot`, published as `build_snapshot_from_wdk` and
  `canonicalize_synced_parameters`. Both ends of it are library shapes, so the
  distribution that owns both shapes owns the conversion.

- One codec states the wire form of a WDK parameter value, and it is the client's.
  `WDK_VOCAB_PARAM_TYPES`, `encode_vocab_value` and `encode_vocab_params` are gone from
  `veupathdb_mcp.wdk`; `encode_param_value` puts one value on the wire for the kind its
  parameter declares. A single pick is now the bare term where this server wrapped it in
  a one-element array, and WDK reads both as the same value. The defaults an analysis
  form offers are carried back as WDK stated them, because a stable value is already a
  wire value. A supplied number takes the canonical form of its kind, so `1.0` reaches
  WDK as `1`, and `merge_analysis_params` refuses a range or a filter value handed to it
  as a wire string rather than passing it through. No served tool's result changes
  shape: the change is in the analysis request this server sends. The client's next
  fixture pass can pin the two forms this rests on: record
  `GET .../steps/{id}/analyses/{analysisName}` for `go-enrichment` and `word-enrichment`
  on one site, which states the declared kind of `organism` and
  `goAssociationsOntologies`, and one `POST .../steps/{id}/analyses` body carrying the
  bare organism term.

- Every `veupathdb` import in `src/` and in `tests/` names a package surface rather than
  a file inside one, at the client's `v0.1.0a9`. The nine shapes the suite builds are
  published, so fifteen imports in the suite name `veupathdb.domain.parameters` or
  `veupathdb.wdk` and none of them names a module. The client publishes no clear of the
  JWKS signing-key cache, and this suite needs none: `reset_site_router` drops the
  router and every per-site client built from it, and `tests/conftest.py` calls it.

- The two visible phyletic species lists are declared once, on
  `veupathdb.domain.parameters`. `PHYLETIC_LIST_PARAMS` is gone from
  `catalog/param_formatting.py` and from this distribution's surface, and its three call
  sites in `catalog/param_formatting.py` and `catalog/param_phyletic.py` read the
  client's constant. `catalog.is_phyletic_sheet` reads the three names off the client's
  `PhyleticBinding` instead of a second pattern constant, which is one declaration
  fewer. The consuming application moves `PHYLETIC_LIST_PARAMS` out of its
  `veupathdb_mcp.catalog` import in `ai/tools/standalone/frame_spec.py` and reads it
  from `veupathdb.domain.parameters`.

- The step tree fold, its refusal and the record type match are the client's.
  `wdk/step_tree.py` and `wdk/record_types.py` are deleted, `build_wdk_step_tree`,
  `MissingWDKStepIdError` and `resolve_record_type` leave this distribution's surface,
  and `wdk/plan_counts.py`, `catalog/record_type_resolution.py`,
  `catalog/param_resolution.py` and `catalog/param_phyletic.py` read the three names
  from `veupathdb.wdk`. The consuming application reads
  `MissingWDKStepIdError` and `build_wdk_step_tree` from `veupathdb.wdk` in
  `services/strategies/sync.py`; it imports neither name from here.

- What a host does to take this release, beyond the pin: read the four credential,
  settings and metadata names from the modules that publish them rather than from the
  root package; delete its own copy of the WDK strategy conversion and import
  `veupathdb_mcp.wdk`; pass its own record type where it passed nothing to
  `gene_sample_attributes`; read `PHYLETIC_LIST_PARAMS` from
  `veupathdb.domain.parameters` and `build_wdk_step_tree` and `MissingWDKStepIdError`
  from `veupathdb.wdk`; and take the client at `v0.1.0a9`, whose surfaces this release
  resolves against. Nothing else in this release moves a published name a host reads:
  the three codec names that left were read by no host.
