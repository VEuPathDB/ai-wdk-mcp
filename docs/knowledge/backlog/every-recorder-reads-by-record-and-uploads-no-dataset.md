---
type: Backlog
title: Every recorder reads by record and uploads no dataset
description: Five recorders under scripts/ still read genes the b35 way, through locus_tag_answers or proteins_of, which upload each gene list as a WDK dataset, or tape only those uploads; each must move to the single record reads the served checks make, and be re-recorded live.
tags: [audit, recorders, fixtures, datasets]
status: draft
---

# What is wrong

A served check reads a named gene by its own record (`audit/record_reads.py`:
`record_rows`, `record_proteins`, at most `RECORD_READS_PER_CALL` genes) and uploads
no gene list, and a host's run list is read the same way (`read_gene_list`). Five
recorders still read the b35 way. `locus_tag_answers` and `proteins_of`
(`audit/genes.py`) upload each gene list as a dataset in the test account, so four of
these write datasets on a QA site, and the fifth tapes only those uploads:

| recorder | read that uploads | read it moves to |
| --- | --- | --- |
| `scripts/record_audit_gene_ids.py` | `locus_tag_answers` for the given gene, its neighbour and the genes the text search matched | the gene record reads `gene_ids` makes for an id (`record_reads.record_rows`), and the text search it already records |
| `scripts/record_audit_introns.py` | `locus_tag_answers` for the gene's row, its protein and its orthologs' proteins | `record_rows` for the row and `record_proteins` for each protein, as `record_audit_records.py` records them |
| `scripts/record_audit_organelle.py` | `locus_tag_answers` for each gene's row and protein | `record_rows` and `record_proteins` |
| `scripts/record_audit_fixtures.py` | `locus_tag_answers` for gene, row and protein answers, and `proteins_of` | `record_rows` and `record_proteins` |
| `scripts/record_audit_missing.py` | its wire (`missing_tgonGT1_nac.json`) holds the two dataset uploads of the b35 row and protein reads; it tapes datasets (`TapedDatasets`) and leaves the record reads the check makes now untaped | the record reads `located` and `read_proteins` make, taped as `record_audit_selenoprotein.py` tapes them (`RecordTape`, `StoreTape`) |

Each wire these recorders write holds locus-tag answers. The recorded tests serve
record reads from those answer bodies (`tests/_support/row_reads.py`), so the wire
does not hold the requests the check sends.

# Change

Rewrite each recorder on the record reads in the table, the way
`record_audit_selenoprotein.py` and `record_audit_records.py` do. Then re-record its
wires live on QA, with one request in flight, a stated budget, and a stop at the first
status of 400 or more. Point the recorded tests at the record exchanges. When no
recorder calls them, remove `locus_tag_answers` and `proteins_of` from the published
surface, together with `TapedDatasets` and `DatasetCall`.

# Done when

`tests/unit/audit/test_recorders_upload_no_dataset.py` runs all five recorders with the
dataset upload refused, and no script under `scripts/` imports `locus_tag_answers` or
`proteins_of`.
