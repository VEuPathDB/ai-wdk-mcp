---
type: Backlog
title: The vocabulary parameter codec is a second answer to the client's question
description: wdk/params.py redeclares the two vocabulary discriminants the client already names in three places, and encodes a single-pick value as a JSON array where the client's own codec sends a bare string.
tags: [wrong-repo, client, parameters]
status: draft
---

# What I did

Read `src/veupathdb_mcp/wdk/params.py` and the client library's parameter value modules
that state the same WDK facts:
`veupathdb-py: src/veupathdb/wdk/wdk_parameters.py`,
`veupathdb-py: src/veupathdb/domain/parameters/values.py` and
`veupathdb-py: src/veupathdb/domain/parameters/value_codec.py`.

# What I got

- `wdk/params.py:21`:
  `WDK_VOCAB_PARAM_TYPES = frozenset({"single-pick-vocabulary", "multi-pick-vocabulary"})`.
- The client names the same two discriminants at `wdk_parameters.py:137` (the parameter
  model's `type` Literal), `values.py:18` (the kind set), `value_codec.py:104` (the
  scalar kinds) and `wdk/strategy_api/base.py:117`.
- The two codecs disagree about the wire form of a single-pick value. This repository,
  `params.py::encode_vocab_value`, returns `json.dumps([value])` for every vocabulary
  param, citing `AbstractEnumParam.convertToTerms()` calling `new JSONArray(stableValue)`.
  The client, `values.py:137::SinglePickValue.to_wire`, returns `self.value`, a bare
  string; only `MultiPickValue.to_wire` calls `json.dumps`.
- `params.py` does no I/O. It imports `flatten_vocab`, `vocab_keys`, `WDKParameter` and
  `JSONObject` from the client and nothing from this distribution.

# Why that's wrong

For the client: one WDK fact has two answers in two repositories, and they contradict
each other. A host that binds a single-pick parameter through the client's codec sends
`PF3D7`, and a host that binds the same parameter through this repository's helpers
sends `["PF3D7"]`. One of those is a parse error in WDK, and nothing decides which,
because the rule that would decide it can only be anchored in one bundle. The same
host, calling both libraries in the same process, gets a different value for the same
parameter depending on which import path the call took.

# Why it happens

`params.py` was written here when parameter binding was built here, and the client grew
its own typed value codec afterwards. Neither deleted the other, and the constant is
declared twice because a `frozenset` is cheaper to retype than to import.

# Fix

In the client library first: move `encode_vocab_value`, `encode_vocab_params` and
`extract_default_params` next to
`veupathdb-py: src/veupathdb/domain/parameters/value_codec.py`, decide the single-pick
wire form against WDK's own source, make `SinglePickValue.to_wire` and the codec agree,
and record the rule in that bundle with its upstream citation. That rides a client
release.

Then in this repository, in the release that follows `0.2.0a4`: delete
`src/veupathdb_mcp/wdk/params.py`, have `wdk/helpers.py` lines 150 and 152 call the
client's functions, drop the four names from `wdk/__init__.py` and from
`tests/unit/published_surface.json`, and raise the client tag in `pyproject.toml`.

The consuming application imports none of the four names directly, so when it takes
both tags nothing in its tree changes.

# What you'd get

One codec, one answer for a single-pick value, and a rule in the client's bundle that a
checker can falsify against WDK's source instead of two constants that cannot both be
right.
