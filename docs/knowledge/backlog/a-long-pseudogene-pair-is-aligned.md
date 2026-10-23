---
type: Backlog
title: A long pseudogene pair is aligned
description: the pseudogene-call check refuses a pair whose reference length times strain window passes PSEUDOGENE_MAX_CELLS, so a long gene called a pseudogene in a strain is never judged.
tags: [audit, pseudogene, tools]
status: draft
---

# What is missing

`_span_refusal` (`audit/served.py`) refuses a pair when the reference length times the
strain window (gene plus `2 * PSEUDOGENE_PAD`) passes `PSEUDOGENE_MAX_CELLS`
(200,000,000), before any sequence read. Measured on QA plasmodb (build 71): PF3D7_0310200
(14,855 bases) against the PfNF54_030015100 pseudogene window (19,628 bases) is
291,573,940 cells, so the unit fails and the finding stays unjudged. Long genes are
where a frameshift call is most likely, so the cap removes the cases the check exists for.

# Change

Align the pair in a bounded way that does not grow with the product of the two lengths:
for example, anchor on the reference's exons and align each exon against its expected
window in the strain, or a banded alignment along the diagonal the gene coordinates give.
Keep the cell bound per piece, not per pair.

# Done when

A served test with the two lengths above judges the pair (a call or a named reason from
the sequence), and a pair that truly cannot be anchored is refused with a reason that
names what was missing, not the cell count.
