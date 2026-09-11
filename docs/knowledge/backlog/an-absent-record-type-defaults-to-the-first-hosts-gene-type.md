---
type: Backlog
title: An absent record type defaults to the first host's gene type
description: gene_sample_attributes treats a missing record type as 'transcript', so an in-process caller with another default gets three gene attributes attached to a step read it did not ask for.
tags: [coupling, tool-payloads]
status: draft
---

# What I did

Read `src/veupathdb_mcp/tool_payloads.py` lines 39 to 50, and its one caller,
`src/veupathdb_mcp/tools/user_tools.py:167`.

# What I got

```
_GENE_RECORD_TYPES = frozenset({"gene", "transcript"})
_GENE_SAMPLE_ATTRIBUTES = ("gene_product", "gene_name", "organism")

def gene_sample_attributes(record_type: str | None) -> list[str] | None:
    """...An absent record type counts as the gene record type the app defaults to."""
    if (record_type or "transcript") in _GENE_RECORD_TYPES:
        return list(_GENE_SAMPLE_ATTRIBUTES)
    return None
```

The docstring names "the app". `tests/unit/test_tool_payloads.py:112` asserts
`gene_sample_attributes(None) == gene_sample_attributes("transcript")`. The served tool
`get_step_sample_records` types `record_type` as a required `str`
(`user_tools.py:150`), so the `None` branch is reachable only from a host that imports
the function.

# Why that's wrong

A second host that imports this package and passes `None` for a step whose record type
is not gene-shaped gets a step read that asks WDK for `gene_product`, `gene_name` and
`organism`. Those three attributes are not the host's request and are not the record
type's attributes, so the read returns columns the host did not ask for, or WDK refuses
the attribute list and the host sees a failed read of a step that is perfectly valid.
The default belongs to the caller: this module cannot know which record type a host
means by silence, and the first host's answer is written into a shared library.

# Why it happens

`gene_sample_attributes` accepts `str | None` and substitutes `"transcript"` for
`None`, a default lifted from the one consumer that had a gene-first product. The
module's own docstring concedes the shape: "the result shapes the MCP server and the
agent toolsets both render".

# Fix

In this repository, in the release that follows `0.2.0a4`: type the parameter
`record_type: str`, delete the `or "transcript"` substitution, and change the assertion
at `tests/unit/test_tool_payloads.py:112` to one that fixes the new signature. The
served tool already requires the argument, so no tool row changes.

When the consuming application takes the tag it passes its own default at the call
site, which is the one place that knows it defaults gene steps to `transcript`.

# What you'd get

A host that means "organism" and says nothing gets an id-only read instead of three
gene attributes, and the sentence "the app defaults to" leaves a library that serves
more than one app.
