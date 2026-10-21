---
type: Decision
title: An audit check reads its genome from the site
description: The two served gene-model checks read every input themselves from the site the call names (gene rows, the gene record, the JBrowse genome window), answer one verdict per call, refuse an input the site cannot give, or a window over the limit, as a tool error and never as a verdict, and run at most two checks at a time in worker threads.
tags: [audit, tools, jbrowse, wdk]
status: stable
---

# The choice

`audit_pseudogene_call(site_id, strain_gene, reference_gene)` and
`audit_selenoprotein_end(site_id, gene, reference_gene)` take gene ids and nothing else.
`veupathdb_mcp.audit.served` reads what each check needs:

- **Where a gene is**: its `GeneByLocusTag` row (`gene_rows`), on the private dataset
  client every dataset upload uses. An id with no row is refused by name. An alias is
  not resolved: the id must be the gene's own source id.
- **Its organism and coding parts**: one gene record read (`gene_model`), attribute
  `organismAbbrev` and table `GeneModelDump`, the CDS rows of the transcript with the
  longest CDS, the lower id on a tie (a row whose `transcript_ids` lists several
  transcripts belongs to each of them). The transcript record declares
  `organismAbbrev` out of its report, so the gene record is the one read that carries
  it. The abbreviation is the JBrowse organism key.
- **The DNA**: a window of the site's JBrowse genome
  (`veupathdb-py: docs/knowledge/wdk/rest/jbrowse-surface.md`). The reference gene is
  read as its own span. The strain gene is padded by `PSEUDOGENE_PAD` (3,000 bases) on
  both sides, so a coding sequence that runs past the annotated span is still read, then
  turned to its own coding strand. A selenoprotein is padded on both sides by
  `SELENOPROTEIN_PAD` (300 bases) plus three bases per residue of the reference tail
  from its first selenocysteine, so a model that stops at a selenocysteine in the middle
  of the protein still has the whole tail in its window.
- **The proteins** of a selenoprotein check: `proteins_of`, the longest transcript's.
  The two checks take the same transcript: the longest coding one.

A later selenocysteine in the reference tail is compared as a stop, since the genome
frame reads its TGA as one; a protein with two selenocysteines still matches.

The pseudogene alignment is `difflib.SequenceMatcher`, whose run time grows with the
product of the two lengths: the reference span and the strain span with both pads. On
an Apple M1 Pro with Python 3.14 it takes 60 to 90 ns per cell: 0.8 s at
2,000 x 8,000, 6.8 s at 8,000 x 14,000, 13.7 s at 12,000 x 18,000 and 23.7 s at
16,000 x 22,000 for a near copy, and 13.1 s at 11,000 x 17,000 for unrelated sequence.
`PSEUDOGENE_MAX_CELLS` (200,000,000) refuses a longer pair before any gene record or
genome read, naming both lengths, so the check stays under about 18 s on that machine.
The served rows of both tools declare a 120 s call budget for the reads around a check
and for the wait for a slot.

Every genome window is at most `AUDIT_MAX_WINDOW_BASES` (250,000) bases: the reference
span, the strain span with both pads and the selenoprotein span with both pads. A
longer window is refused before any gene record or genome read, naming the gene, the
window length and the limit. The selenoprotein check translates its window in six
frames: 0.07 s at 250,000 bases and 1.1 s at 4,000,000 on the machine above. The
pseudogene cell limit admits a 250,000 base strain window only for a reference of at
most 800 bases, and with the 6,001 base minimum of a padded strain window it keeps
the reference under 33,328 bases.

Both checks run in a worker thread (`asyncio.to_thread`), so the event loop of the
served process keeps answering other calls during a check. The checks are pure Python
and hold the interpreter lock, so a process runs at most two of them at once: the
event loop shares the lock with two checks at most, and a short selenoprotein check
does not wait behind one long alignment. A further call
waits for a slot and is not refused. A call that is cancelled keeps its slot until its
thread ends, because the thread cannot be stopped. Each event loop has its own two
slots, so a host that runs the tools under several loops in turn is not refused. The
bound is per process: N served processes run up to 2N checks.

The genetic code is the standard one for every organism in this release.

Every input the site cannot give (an unknown id, a reference with no CDS rows, a gene
with no protein, a selenoprotein reference with no selenocysteine, a pair too long to
align, a window over the limit, a gene record with no organism, a WDK refusal, a truncated report, a sequence
the genome index lacks, a JBrowse error, a site that does not answer) is a tool error
that names it, as `tests/unit/audit/test_audit_tools.py` shows.

Both answers are `CamelModel`s, like every other served result, so their keys are
camelCase on the wire (`referenceGene`, `afterModelEnd`, `residueDifferences`).

# What was rejected

**The caller passes the sequences.** A host would have to read a genome window itself,
and the check would answer for DNA nobody can trace back to a site build. Reading the
inputs here keeps one call one verdict about named genes.

**A verdict for an input that is missing.** `MODEL_NOT_FOUND` already means the model
protein was not found in the genome. Reusing it, or adding an `UNKNOWN_GENE` verdict,
would let a typo in a gene id read as a finding about the annotation.
