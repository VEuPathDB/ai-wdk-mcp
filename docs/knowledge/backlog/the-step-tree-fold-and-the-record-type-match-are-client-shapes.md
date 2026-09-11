---
type: Backlog
title: The step tree fold and the record type match are client shapes living here
description: build_wdk_step_tree folds the client's own AST with the client's own fold, and resolve_record_type matches a string against the client's WDKRecordType; neither touches a catalog, a tool or the index.
tags: [wrong-repo, client, wdk]
status: draft
---

# What I did

Read `src/veupathdb_mcp/wdk/step_tree.py` and `src/veupathdb_mcp/wdk/record_types.py`,
listed their imports, and read the client module they belong beside,
`veupathdb-py: src/veupathdb/wdk/step_tree.py`.

# What I got

- `wdk/step_tree.py:23::build_wdk_step_tree` folds a `StrategyStepNode` into a
  `WDKStepTree`. Every name it uses is the client's:
  `veupathdb.domain.strategy.ast.StrategyStepNode`,
  `veupathdb.domain.strategy.tree.fold`, `veupathdb.wdk.wdk_models.WDKStepTree`, and
  `VEuPathDBError` for `MissingWDKStepIdError`. It imports nothing from this
  distribution.
- `wdk/record_types.py:19::resolve_record_type` matches a string against
  `veupathdb.wdk.wdk_models.WDKRecordType` on `url_segment`, then `full_name`, then a
  unique `display_name`. It also imports nothing from this distribution.
- The client already holds the traversal of the same shape:
  `step_tree.py:6::walk_wdk_step_tree`.
- Callers here are `catalog/record_type_resolution.py:36`, `catalog/param_resolution.py:71`
  and `catalog/param_phyletic.py`, all of which pass a record type list the catalog
  already read. The consuming application imports the step tree pair directly at
  `pathfinder: apps/api/src/pathfinder/services/strategies/sync.py`, line 22.

# Why that's wrong

For the client: `WDKStepTree` and `WDKRecordType` are the client's types, and the two
functions that build and match them live in a tool server that not every host of the
client deploys. A host that uses the client library alone has to write its own fold of
the client's own AST into the client's own tree, or take an MCP server it does not
serve. The client's bundle anchors the step tree rules, so a rule about the tree points
at a function in a repository it cannot see, and the tree can be built two ways with
nothing comparing them.

# Why it happens

Both functions were written where their first caller was. `resolve_record_type` was
needed by the catalog's parameter resolution and `build_wdk_step_tree` by the step
push, so each landed in `veupathdb_mcp.wdk` beside the code that called it rather than
beside the type it constructs.

# Fix

In the client library first: move `build_wdk_step_tree` and `MissingWDKStepIdError`
into `veupathdb-py: src/veupathdb/wdk/step_tree.py` beside `walk_wdk_step_tree`, and
`resolve_record_type` beside `WDKRecordType` in `veupathdb/wdk/wdk_models.py` or its own
module. That rides a client release.

Then in this repository, in the release that follows `0.2.0a4`: delete
`src/veupathdb_mcp/wdk/step_tree.py` and `src/veupathdb_mcp/wdk/record_types.py`, point
the three catalog callers at the client, drop the names from `wdk/__init__.py` and from
`tests/unit/published_surface.json`, and raise the client tag in `pyproject.toml`.

When the consuming application takes both tags it edits one import line, in
`services/strategies/sync.py`, from this distribution to the client.

# What you'd get

A host that takes the client library alone can fold a plan into a WDK step tree and
match a record type, and the client's bundle anchors its step tree rules to functions in
its own repository.
