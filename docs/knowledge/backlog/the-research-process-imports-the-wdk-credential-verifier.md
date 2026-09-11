---
type: Backlog
title: The research process imports the WDK credential verifier it never uses
description: Reading __version__ from the root package pulls the WDK auth module, the OAuth subject cache and the full McpSettings into a process that has no account, no site and no database.
tags: [coupling, research, imports]
status: draft
---

# What I did

Imported the research server on an interpreter that held nothing else, and listed the
modules of this distribution that the import loaded:

```
.venv/bin/python -c "import sys, veupathdb_mcp.research.server; print(sorted(m for m in sys.modules if m.startswith('veupathdb_mcp')))"
```

# What I got

30 modules of this distribution, 8 of them outside `veupathdb_mcp.research`:
`veupathdb_mcp`, `veupathdb_mcp.auth`, `veupathdb_mcp.identity`,
`veupathdb_mcp.metadata`, `veupathdb_mcp.service_tokens`, `veupathdb_mcp.settings`,
`veupathdb_mcp.tool_errors`, `veupathdb_mcp.tool_meta`. `veupathdb.wdk.auth_login` from
the client library is loaded too.

The chain is one line: `research/server.py:16` reads `from veupathdb_mcp import
__version__`, and the root `__init__.py` lines 8 to 22 import `veupathdb_mcp.auth`,
which imports `veupathdb_mcp.identity` and `veupathdb_mcp.settings`.
`identity.py:21::resolve_oauth_subject` is the OAuth subject cache, and `McpSettings`
parses `WDK_MCP_SERVICE_TOKENS`. The research server has its own credential path,
`research/auth.py::ServiceTokenVerifier`, and reads none of this.

# Why that's wrong

The research image is deployed as a process that holds no account, no site catalog and
no database, and its README says so. What it actually loads is the WDK server's
credential verifier and its OAuth subject cache, so an operator auditing the research
container finds VEuPathDB OAuth code in a process that is supposed to verify a service
secret and nothing else, and any import-time failure in the WDK settings or identity
modules takes down a server that does not use them. The blast radius of a change to
`auth.py` silently includes the research process.

# Why it happens

`research/server.py` reads the version from the root package, and the root
`__init__.py` re-exports the WDK server's auth surface. There is no module that holds
the version alone.

# Fix

In this repository, in the release that follows `0.2.0a4`: put `__version__` in a
module that imports nothing from this distribution, have the root `__init__.py` read it
from there, and have `research/server.py` read it from there too. Extend
`tests/unit/test_package_boundary.py` with an assertion that importing
`veupathdb_mcp.research.server` loads no `veupathdb_mcp.auth`, `veupathdb_mcp.identity`
or `veupathdb_mcp.settings`, which is the gate that keeps the two processes apart.

When the consuming application takes the tag nothing changes for it: it imports the WDK
side, and every name the root package publishes stays where it is.

# What you'd get

The research process loads its own settings, its own service-token verifier and the two
tool modules, and an edit to the WDK credential path cannot break the process that
serves literature and web search.
