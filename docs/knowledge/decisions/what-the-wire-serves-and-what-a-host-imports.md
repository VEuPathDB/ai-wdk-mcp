---
type: Decision
title: What the wire serves, and what a host imports
description: A published name gets a tool row when the call takes values and returns values; a name whose contract includes a Python object the caller supplies, or a write into the deployment's own store, stays an in-process import.
tags: [tools, server, generality]
status: stable
---

# The choice

Twenty-five tools are served on `veupathdb-wdk-mcp`, against 275 names published for
in-process import across sixteen surfaces. The line is one property:

**A call is served when its arguments and its result are values.** A call whose
contract includes a Python object the caller builds, or a write into a store the
deployment owns rather than the caller, is not served.

A served tool carries the same contract as the in-process call it wraps: the same
result model, and the same refusals as tool errors. Where the in-process call takes a
seam the wire cannot carry, the tool builds that seam from the site the call already
names, and nothing else changes.

# What that admitted

Eight capabilities that had no tool row and now have one:

| tool | the published call it serves |
| --- | --- |
| `resolve_search_parameters` | `resolve_params_with_intent`, over `wdk_fetch_at` |
| `validate_search_parameters` | `validate_parameters`, over `make_validation_callbacks` |
| `get_search_param_specs` | `build_param_specs`, over the search the site catalog resolves |
| `search_catalog_index` | `search_index`, over `catalog_index_id` |
| `count_plan_steps` | `compute_plan_step_counts` |
| `run_control_tests_on_step` | `run_step_control_tests` |
| `create_gene_set_step` | `frozen_step_id` |
| `get_step_gene_ids` | `fetch_gene_ids_from_step`, over `get_strategy_api` |

# What stays in process, and why

- `make_validation_callbacks` returns a `ValidationCallbacks` of coroutines. A callable
  is not a value, and the wire has no form for one. The served tool builds the
  callbacks from its `site_id`, which is the only argument they take.
- `sync_index` writes vectors into the deployment's own database. The process that
  refreshes is not the process that serves (`EMBEDDING_INDEX_SYNC_ENABLED`), so a
  served form would let a caller re-embed a store it does not own.

# What was rejected

**Serving every published name.** Most of the 275 are result models, error types and
the small functions those are built from. A tool row for each would publish an API
surface no client can hold in a context window, and the conformance suite reads every
row of `tools/list` on every call.

**Leaving the line unstated and letting the first host's appetite decide.** That is how
seventeen rows came to stand for the whole library: a capability reached the wire only
when the first host wanted it there, and that host imports the package in process.
