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
  `pg_advisory_xact_lock(hashtextextended(search_line_key(site_id), 0))` in the blocking
  form, in a `READ COMMITTED` transaction it opens on a connection of the engine it was
  given, whatever that engine's own isolation level. The lock is transaction-scoped: the
  commit at the end of the request, the rollback after an error or a cancellation, and
  the pool's reset on return each free it, so a pooled connection never goes back to
  its pool holding the line. A process that dies loses its session, which frees it too.
  In front of it, each process queues its own requests per site on an `asyncio.Lock`,
  so it holds at most one line connection per site.
- **Its connections.** `install_search_line(database_url, expensive, *, pool_size=1,
  max_overflow=1, pool_timeout=None)` builds the line's own pooled engine and returns
  it, so the host disposes it. A request holds its connection for the whole search, so
  a process runs at most `pool_size + max_overflow` expensive searches at once across
  its sites, and the rest wait for a connection. The line itself waits without a limit
  (the lock is the blocking form, and a request's budget starts at its send), so the
  pool's wait has none either by default. The served process reads
  `SEARCH_LINE_POOL_SIZE`, `SEARCH_LINE_MAX_OVERFLOW` and
  `SEARCH_LINE_POOL_TIMEOUT_SECONDS`. A host that builds `ExpensiveSearchLine` on its own
  engine keeps its own pool.
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
- **A session-scoped lock on a pooled connection.** An error or a cancellation between
  the lock and the unlock returns the connection to the pool with the lock still held,
  and the next request on that connection takes it again on top.
- **A connection per site (`NullPool`).** A deployment of 14 sites opens up to 14
  connections in each process, past what one Postgres gives a process.
