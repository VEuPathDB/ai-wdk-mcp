---
type: Backlog
title: A strain longer than its relatives has a side
description: audit_strain_model answers UNCLEAR for a strain model longer than its reference even when the reference sits at its relatives' median and the strain does not, so a strain model that is too long has no side of its own.
tags: [audit, strain, tools]
status: draft
---

# What is missing

`tie_break` (`audit/strain.py`) names `STRAIN_SHORT` and `REFERENCE_LONG` only, and a
strain longer than its reference is `UNCLEAR`. Of the prototype's 628 strain-short
arbitrations, 10 have a strain at least as long as its reference. One is plain:
PVW1_120049800 on plasmodb, a strain of 2,181 residues against a reference of 1,199,
whose relatives' median is 1,173.

# Change

Add a `STRAIN_LONG` side: the strain is longer than its reference, the reference is
within `RELATIVES_WITHIN` of its relatives' median and the strain is not. Decide first
what DNA evidence it needs, because the length check confirms a segment the strain
lost, not one it gained.

# Done when

A served test with PVW1_120049800's lengths and relatives answers `STRAIN_LONG`, and a
strain longer than its reference with relatives that agree with neither stays
`UNCLEAR`.
