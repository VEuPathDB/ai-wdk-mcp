---
type: Backlog
title: The WDK server proves admission in another repository, at an older conformance pin
description: This repository's CI runs the conformance suite against the research server on 8110 only, at v0.2.0a2; the 8100 lane lives in the consuming application's nightly workflow, needs that application's database schema, and the application itself installs v0.3.0a5.
tags: [generality, ci, conformance]
status: draft
---

# What I did

Read `.github/workflows/ci.yml` in this repository, then the nightly workflow and the
backend pin in the consuming application: `pathfinder: .github/workflows/mcp-nightly.yml`
and `pathfinder: apps/api/pyproject.toml`.

# What I got

- `ci.yml:48` opens `research-conformance`, and `ci.yml:57` pins
  `veupathdb-mcp-conformance` at `v0.2.0a2`. Its endpoint is
  `http://localhost:8110/mcp`, and the server it starts is
  `python -m veupathdb_mcp.research`. There is no job in this file that starts
  `python -m veupathdb_mcp`, the WDK server on 8100.
- The 8100 lane is `mcp-nightly.yml` in the application. Before it starts the server it
  runs `pathfinder.platform.migrations.init_db()` against
  `postgresql+asyncpg://postgres:postgres@localhost:5432/pathfinder_test`, because a
  user bearer in that lane names a row in the application's own schema.
- The application installs the conformance suite at `v0.3.0a5`
  (`pathfinder: apps/api/pyproject.toml`, line 63). This repository's lane is three
  alpha tags behind it.

# Why that's wrong

A deployment admits an MCP tool server only after the conformance suite passes against
it. A second host reading this repository finds passing evidence for the literature and
web search server and none for the WDK server, which is the one it came for. The only
lane that produces that evidence needs a `pathfinder_test` database and the
application's migrations, so the second host cannot run it either, and cannot tell
whether a failure is the server's or the application's. Meanwhile the two lanes read
different suites: a conformance rule added between `v0.2.0a2` and `v0.3.0a5` is
enforced on the research server by nobody and on the WDK server only in a repository
this one does not control.

# Why it happens

The WDK server's `WdkIdentity` middleware verifies a user bearer against the deployment
that issued it, and the first deployment to run this lane was the application, whose
users live in its own tables. The lane was written where the users were, so the job
that would have lived in `ci.yml` was never written, and the `CONFORMANCE` pin in
`ci.yml` was set once for the server that needed no account and then not moved.

# Fix

In this repository, in the release that follows `0.2.0a4`:

1. A `wdk-conformance` job in `ci.yml` that starts `python -m veupathdb_mcp` with
   `WDK_MCP_SERVICE_TOKENS` set to a lane-local service secret, so admission is proven
   in service mode with no account and no application schema, and uploads its
   `admission-report.json` beside the research one.
2. The same `CONFORMANCE` pin for both jobs, moved to the tag the consuming application
   installs.
3. A page in this bundle naming the two lanes and the property that makes the WDK lane
   runnable here: a service secret is issued by the deployment, so admission needs no
   user row.

When the application takes the tag, its nightly lane keeps its user-bearer run, which
now tests the application's own identity wiring rather than standing in for the
server's admission.

# What you'd get

`ci.yml` produces two admission reports on every push, both at the conformance tag the
consuming application installs, and a second host reads passing evidence for the server
it deploys without provisioning another application's database.
