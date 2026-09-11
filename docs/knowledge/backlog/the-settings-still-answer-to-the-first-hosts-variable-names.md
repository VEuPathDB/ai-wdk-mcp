---
type: Backlog
title: The settings still answer to the first host's variable names
description: McpSettings accepts PATHFINDER_MCP_BASE_URL and PATHFINDER_MCP_SERVICE_TOKENS as alias choices, the README promises their removal after one release, and no repository sets either name.
tags: [coupling, settings]
status: draft
---

# What I did

Read `src/veupathdb_mcp/settings.py` lines 30 to 44, then searched all four checkouts
for anything that sets either variable.

# What I got

- `settings.py:36`:
  `validation_alias=AliasChoices("WDK_MCP_BASE_URL", "PATHFINDER_MCP_BASE_URL")`.
- `settings.py:41` to 43: the same pair for `WDK_MCP_SERVICE_TOKENS` and
  `PATHFINDER_MCP_SERVICE_TOKENS`.
- `README.md:156`: "read as the old names of the first two for one release, and then
  removed". The release is not named, and no test or gate fails when it passes.
- Producers of either environment variable across the four checkouts: none. The
  consuming application sets `WDK_MCP_SERVICE_TOKENS`
  (`pathfinder: .github/workflows/mcp-nightly.yml`, lines 54 and 82); the value comes
  from a GitHub secret that still carries the old name, which is a secret's name and
  not a variable this package reads. The only readers left are two tests in this
  repository, `tests/unit/server/test_settings_source.py` lines 54 and 67 and
  `tests/unit/research/test_settings.py:33`.

# Why that's wrong

The alias is a promise this package makes to one host, in that host's name, in a
settings model every other host loads. A second host reading `McpSettings` sees an
application it does not deploy named in its own configuration surface, and cannot tell
whether setting the old name is supported, deprecated or about to be deleted, because
nothing dates or gates the removal. The deprecation window is over by measurement: no
deployment supplies either name.

# Why it happens

`McpSettings` was extracted from the application's settings when the server left it,
and `AliasChoices` was the cheapest way to keep the running deployment up during the
move. Nothing was written that would fail once the move was done, so the aliases
outlived their reason.

# Fix

In this repository, in the release that follows `0.2.0a4`: delete the second choice
from both `AliasChoices` calls in `settings.py`, delete the README paragraph at line
156, and change the three tests that set the old names to set the new ones.

When the consuming application takes the tag, nothing in it changes: it already sets
`WDK_MCP_SERVICE_TOKENS`. Renaming the GitHub secret behind that value is the
application's own housekeeping and does not block the release.

# What you'd get

`McpSettings` names no application, and a host reading the settings model sees one
environment variable per setting instead of one supported name and one undated
promise.
