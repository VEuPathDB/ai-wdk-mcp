# Knowledge log

## 2026-09-11

- The client pin is `v0.1.0a10`, the release that publishes the signing-key reset, so
  a host that pins both distributions resolves one client URL. `veupathdb-mcp` is 0.2.0a6.

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
