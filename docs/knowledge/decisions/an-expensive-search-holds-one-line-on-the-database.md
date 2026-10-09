---
type: Decision
title: An expensive search holds one line on the database
description: veupathdb_mcp.search_line is the one implementation of the line every process of a deployment shares: a Postgres advisory lock per site, held for the request, which the served process installs at startup and a host installs in its own processes. The served process runs each tool call as one search turn. A line per process, a refusal at the limit and Redis were rejected.
tags: [wdk, load, searches, postgres]
status: stable
---

# The choice

`veupathdb-py` passes every request that runs a search through a gate the host installs
(`veupathdb-py: docs/knowledge/decisions/a-search-waits-in-line-and-the-host-owns-the-gate.md`).
`veupathdb_mcp.search_line` is that gate for a deployment of several processes.

- **The line.** `ExpensiveSearchLine.hold(site_id)` takes
  `pg_advisory_lock(hashtextextended(search_line_key(site_id), 0))` in the blocking form
  on a connection of its own (`NullPool`, autocommit), and unlocks when the request ends.
  An error or a cancellation closes the connection, and a process that dies loses its
  session; either frees the lock. In front of it, each process queues its own requests
  per site on an `asyncio.Lock`, so it holds at most one line connection per site.
- **Who waits.** `search_line_gate(line, expensive)` sends a request through the line
  when `expensive(request)` holds; the default is `runs_an_expensive_search`, the High
  Speed SNP searches. A host passes its own rule.
- **Who installs it.** `python -m veupathdb_mcp` installs it at startup on the
  database its index uses (`DATABASE_URL`); with none, the process keeps the client's open
  gate. A host installs the same function in its own processes, so every process names
  the same lock. `SearchTurnPerCall` runs each served tool call as one `search_turn`, so a
  call's fan-outs send one search per site at a time.
- **What a wait says.** Every wait is reported to the client's observer
  (`on_wdk_search_wait`, line `expensive`). A wait longer than `NOTICE_SECONDS` (5) calls
  the `SearchWaitListener` the caller set with `told_while_waiting`, and again when the
  search starts; the host chooses the words.

# Order

Postgres grants an exclusive advisory lock to its waiters in the order they asked; the
integration suite measures four processes queued one after another taking it in arrival
order, and one process's own requests taking it in the order they queued.

# What was rejected

- **A line per process.** A deployment runs several processes against one site.
- **A refusal at the limit.** A caller would see an error for load it did not cause.
- **Redis.** The deployments that run this server run Postgres already.
