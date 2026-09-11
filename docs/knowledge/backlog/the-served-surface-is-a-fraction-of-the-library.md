---
type: Backlog
title: The served surface is a fraction of the library, and nothing says so
description: Seventeen tools are served over the wire while 269 names are published for in-process import, so a host that only speaks MCP can read the catalog and cannot build a strategy.
tags: [generality, tools, server]
status: draft
---

# What I did

Counted the rows of `TOOLS` in `src/veupathdb_mcp/server.py` (lines 134 to 163),
counted the names in `tests/unit/published_surface.json`, and counted the import lines
that name this package in the consuming application's backend tree
(`pathfinder: apps/api/src`).

# What I got

- 17 tool rows, and `veupathdb_mcp.tools` publishes exactly those 17 names:
  `list_record_types`, `search_for_searches`, `browse_search_categories`,
  `list_searches`, `list_transforms`, `lookup_phyletic_codes`, `search_example_plans`,
  `get_search_overview`, `get_parameter_options`, `lookup_gene_records`,
  `get_ai_expression_summary`, `resolve_gene_ids_to_records`,
  `get_step_estimated_size`, `get_step_sample_records`, `get_step_download_url`,
  `run_control_tests_on_search`, `enrich_gene_ids`.
- 269 published names across 13 surfaces: `veupathdb_mcp` 15, `.catalog` 83, `.controls`
  14, `.embeddings` 32, `.gene_lookup` 12, `.migrate` 4, `.research` 20, `.server` 5,
  `.tool_meta` 2, `.tool_payloads` 11, `.tools` 17, `.wdk` 35, `.wdk.enrichment` 19.
- 195 import lines in the application name this package.
- Eleven of the published names that carry the work beyond a catalog read have no tool
  row at all: `validate_parameters`, `make_validation_callbacks`, `build_param_specs`,
  `ResolvedParams` (`veupathdb_mcp.catalog`); `build_wdk_step_tree`,
  `compute_plan_step_counts`, `frozen_step_id`, `fetch_gene_ids_from_step`
  (`veupathdb_mcp.wdk`); `run_step_control_tests` (`veupathdb_mcp.controls`);
  `search_index`, `sync_index` (`veupathdb_mcp.embeddings`).

# Why that's wrong

A second host reads the README, sees a served MCP endpoint with seventeen tools, and
builds against it. It gets search discovery and record reads, and then has no way to
bind a parameter, no way to fold a plan into a WDK step tree, no count for a step it
has not run, no control test on a step and no semantic search over the catalog. Those
are the calls that turn a search listing into a strategy, and over the wire they do not
exist. The host finds this out after it has written its client, because nothing in this
repository states the line between the served product and the imported one.

# Why it happens

`server.py::TOOLS` is a hand-written tuple. A capability reached it only when the first
host wanted that capability over the wire, and the first host imports the package in
process, so every capability it could call directly stayed unserved and unnamed.

# Fix

In this repository, in the release that follows `0.2.0a4`:

1. A decision page in this bundle that draws the line: which surfaces are served, which
   are in-process only, and the property that decides it (a surface that needs the
   caller to hold state between calls is not served).
2. Tool rows for the surfaces that hold no caller state across calls, at minimum
   `validate_parameters`, `build_param_specs`, `compute_plan_step_counts`,
   `run_step_control_tests` and `search_index`, each with its annotations and its
   `MAX_CALL_SECONDS_META_KEY` where the call is long.
3. A README paragraph naming the in-process seam for the rest.

The consuming application takes the tag by changing it in
`pathfinder: apps/api/pyproject.toml` and in both MCP build contexts in
`pathfinder: docker-compose.yml`, then `uv lock --upgrade-package veupathdb-mcp` and
`uv sync`. Its own calls are unchanged: the new rows are additive, and no published
name moves.

# What you'd get

A host that speaks only MCP can discover a search, bind and validate its parameters,
count the plan it assembled and run control tests on it, and a host that cannot do the
rest over the wire reads which calls need in-process import before it writes a client
rather than after.
