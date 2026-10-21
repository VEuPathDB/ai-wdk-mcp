---
type: Decision
title: A step read is bounded by its caller
description: Reading the ids of a built step takes a record limit the caller passes, asks WDK for one record more, and refuses a larger step with StepTooLargeError; every other record read here is bounded by its own input, and no read cuts an answer short in silence.
tags: [wdk, gene-sets, payloads]
status: stable
---

# The choice

`fetch_gene_ids_from_step` and `resolve_wdk_context` (`veupathdb_mcp/wdk/gene_set_steps.py`)
take a required `limit`. A limit below 1 raises `ValueError` before any request. The report
asks for `limit + 1` records, and a step that returns more than `limit` records raises
`StepTooLargeError`, a `veupathdb.errors.ValidationError` (422) that keeps `step_id` and
`limit`. The count is of records, not of the ids read from them, so a record without an id
does not hide one record past the limit.

`resolve_wdk_context` lets every site refusal out: the refusal, a failed root-step read and
a failed report all raise. None of them reads as an empty step. The served
`get_step_gene_ids` passes `MAX_GENE_IDS` and turns the refusal into a tool error that names
`get_step_download_url`.

The other record reads of this library are bounded by their own input:

- A control test reads only an intersection with the controls, at most
  `TRANSCRIPTS_PER_GENE` records per control id, and refuses a larger answer
  (`a-control-test-files-every-id-it-was-given.md`).
- `resolve_gene_ids` asks for `TRANSCRIPTS_PER_GENE` (8) records per id, the bound the
  audit's locus-tag read already uses, and answers an error result when WDK holds more.
- Previews, counts, the text lookup and the audit reports send an explicit `numRecords`.
  The OrthoMCL taxonomy report reads one helper record, and the catalog build reads the
  site's dataset list once.

# What was rejected

**A read of every record (`numRecords: -1`).** WDK then sends the whole answer in one body.
An OrthoMCL protein step can hold several hundred thousand records, so one call can move
hundreds of megabytes from the site while a turn waits.

**Cutting the step at the limit.** A host that stores or compares the ids would hold a part
of the step as if it were the whole step, and nothing in the result would say so.

**One cap in the library.** The bound depends on what the host does with the ids: a tool
call answers a few hundred, a saved set holds more. The host knows its bound, so it names it.

**An empty step for a failed read.** A host stores an empty set for a strategy that is not
empty, and nothing tells the researcher that the site refused.

# What would prove this wrong

`tests/unit/wdk/test_a_step_read_is_bounded.py`: a step of 2 under a limit of 2 is read with
`numRecords: 3`, a step of 3 under the same limit is refused even when one record has no id,
a limit of 0 or -1 sends no request on either path, and a site refusal raises.
`tests/unit/gene_lookup/test_a_lookup_is_bounded.py`: two ids send `numRecords: 16`, and an
answer of 17 records is an error result.
