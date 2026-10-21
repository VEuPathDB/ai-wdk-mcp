---
type: Backlog
title: A clade code names its species count
description: lookup_phyletic_codes returns code, label and leaf for each match, so a model cannot write an OrthoMCL expression that needs the number of species under a clade, such as one copy in every species of a clade.
tags: [orthomcl, phyletic, catalog, tools]
status: draft
---

# What is missing

`lookup_phyletic_codes` (`catalog/param_phyletic.py`) returns each match as
`{"code", "label", "leaf"}`. On OrthoMCL, a phyletic expression that asks for
exactly one copy in every species of a clade is `<CLADE>=<N>T AND <CLADE>=<N>`,
where N is the number of species under the clade: every species present, and as
many sequences as species. Without N the expression cannot be written.

# Change

For a match with `leaf=false`, add the number of leaf species under it from the
taxonomy tree the lookup already reads, and state in the lookup hint how a count
and a `T` count combine to express one copy per species.

# Done when

A lookup of `Apicomplexa` on OrthoMCL QA returns the APIC code with its species
count, and a unit test covers the count for a clade with nested clades.
