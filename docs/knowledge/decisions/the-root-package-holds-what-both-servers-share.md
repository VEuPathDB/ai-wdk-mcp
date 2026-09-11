---
type: Decision
title: The root package holds what both servers share
description: Importing any module of a package runs that package's __init__, so keeping the WDK credential path out of the research process is a question of what the root re-exports, not of where the version literal lives.
tags: [imports, research, generality]
status: stable
---

# The choice

`veupathdb_mcp/__init__.py` re-exports three leaf modules only: the service-token
registry, the tool error payload and the tool metadata keys. The WDK credential path,
its settings and its published metadata each declare their own surface, read by module
name (`veupathdb_mcp.auth`, `veupathdb_mcp.settings`, `veupathdb_mcp.metadata`),
beside `veupathdb_mcp.server`, `veupathdb_mcp.migrate` and
`veupathdb_mcp.tool_payloads`, which were already there.

`tests/unit/research/test_import_boundary.py` holds the line: a fresh interpreter that
imports `veupathdb_mcp.research.__main__` loads none of those three modules.

# Why a version module alone would not have done it

The obvious fix is a module that holds `__version__` and imports nothing, read by the
research server instead of the root package. It changes nothing: Python runs a
package's `__init__` before any module inside it, so `from veupathdb_mcp.version import
__version__` loads exactly what `from veupathdb_mcp import __version__` loads. The
research process imports `veupathdb_mcp.research`, so it runs the root `__init__`
whatever the version reads from. The only thing that keeps the WDK credential verifier
and the OAuth subject cache out of a process with no account is the root importing
less.

# The cost

A host reading `McpSettings`, `wdk_identity` or `RESOURCE_NAME` names the module rather
than the package. That is the rule this distribution already follows for the server,
the migration chain and the tool payloads, and the surface test checks each module's
`__all__` against the checked-in copy, so a name cannot leave one quietly.
