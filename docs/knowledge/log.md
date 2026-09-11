# Knowledge log

## 2026-09-11

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

- What a host does to take this release, beyond the pin: read the four credential,
  settings and metadata names from the modules that publish them rather than from the
  root package; delete its own copy of the WDK strategy conversion and import
  `veupathdb_mcp.wdk`; and pass its own record type where it passed nothing to
  `gene_sample_attributes`. Nothing else in this release moves a published name.
