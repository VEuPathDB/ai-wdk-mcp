---
type: Backlog
title: A lookup reads by record, and a tool that writes a dataset says so
description: Six served tools outside the audit write a WDK dataset into the caller's account, which WDK cannot delete; two of them are annotated read-only. The lookups must read named genes by record, and the tools that need a dataset must state it.
tags: [datasets, tools, annotations]
status: draft
---

# What is wrong

These served tools reach `StrategyAPI.create_dataset`, so each call leaves an id-list
dataset in the researcher's WDK account, and WDK has no dataset delete:

- `resolve_gene_ids_to_records` and `lookup_gene_records`, both annotated read-only;
- `enrich_gene_ids`;
- `run_control_tests_on_step` and `run_control_tests_on_search`;
- `create_gene_set_step`.

# What changes

- The two lookups read each named gene by its own record (`audit/record_reads.py`:
  `record_rows`, bounded by `RECORD_READS_PER_CALL`), with the text-search fallback for an
  id that names no record, and stay read-only in fact.
- The tools whose WDK search takes only an id list (enrichment, control tests, a gene-set
  step) state in their descriptions that they write one dataset into the account, and drop
  any read-only annotation.
- A dataset trap test runs every served tool and lists the ones that write a dataset; the
  list equals the tools whose description says so.

# How it is checked

The trap test above, and the recorded wires of the two lookups re-recorded on QA with no
dataset call.
