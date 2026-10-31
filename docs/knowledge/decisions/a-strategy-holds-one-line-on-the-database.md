---
type: Decision
title: A strategy holds one line on the database
description: veupathdb_mcp.strategy_line is the gate a deployment installs for veupathdb-py's strategy requests. Each request on one strategy holds the Postgres advisory lock wdk-strategy:<site>:<strategy id> on a session of the host's own pool, behind one in-process lock per strategy. The served process installs it on the index's sessions; a host installs it on its own. A pool of its own and a lock per site were rejected.
tags: [wdk, strategy, postgres, load]
generated: { by: claude-code/opus-5.5, at: 2026-10-31T00:00:00Z }
verified: { by: claude-code/opus-5.5, at: 2026-10-31T00:00:00Z }
status: stable
---

# What was decided

WDK saves a strategy on every read, `PATCH` and `DELETE`, so a request beside a
`PUT .../step-tree` on the same strategy can restore the old tree
(`veupathdb-py: docs/knowledge/wdk/rules/strategies-and-steps.md`, WDK-STRAT-008). The
client passes every request on one strategy through a gate the host installs
(`use_strategy_gate`, the same decision as its search gate,
`veupathdb-py: docs/knowledge/decisions/a-search-waits-in-line-and-the-host-owns-the-gate.md`).

`install_strategy_line(open_session)` installs `StrategyLine.hold` as that gate. A hold
waits for the process's own lock on the strategy, opens one session, and takes
`pg_advisory_xact_lock(hashtextextended('wdk-strategy:<site>:<strategy id>', 0))`; the
session's close ends the transaction and frees the lock. So one process opens at most one
session per strategy, and every process on one database sends one request per strategy at
a time. The control tests' read of a step's strategy, and every other strategy request
this package sends, goes through the client and so through the gate.

The served process installs it on `embedding_session` when it has a database. A host
installs it on the session factory of its own pool.

# What was rejected

- **A pool of its own.** A small pool would hold every strategy request of the process
  to its size, across researchers; one request holds a session for one WDK request only.
- **A lock per site.** Requests on different strategies do not overwrite each other and
  would wait for nothing.
