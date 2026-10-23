---
type: Backlog
title: A parameter says it takes pasted text
description: ParameterInfo drops WDK's isMultiLine, so a host that must tell a pasted-sequence parameter from a short free-text value reads the raw search definition instead of the catalog.
tags: [catalog, parameters, wdk]
status: draft
---

# What is wrong

WDK marks a string parameter that takes pasted text (a BLAST query sequence) with
`isMultiLine`. `veupathdb_mcp.ParameterInfo` does not carry it, so PathFinder reads the raw
`WDKSearch` definition to know a slot takes pasted text and no readings.

# What changes

`ParameterInfo` gains `multi_line: bool` from `isMultiLine`, published on the catalog surface
and in the served parameter payloads; PathFinder then reads it from the catalog.

# How it is checked

A recorded search definition with a multi-line parameter round-trips into `ParameterInfo`
with `multi_line` true, and a short string parameter with it false.
