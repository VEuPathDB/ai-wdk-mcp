---
type: Decision
title: An audit check reads its genome from the site
description: The served gene-model checks read every input themselves from the site the call names (gene rows, the gene record, the ortholog group, the JBrowse genome window), answer one verdict per call, refuse an input the site cannot give, or a window over the limit, as a tool error and never as a verdict, and run at most two checks at a time in worker threads.
tags: [audit, tools, jbrowse, wdk]
status: stable
---

# The choice

`audit_pseudogene_call(site_id, strain_gene, reference_gene)`,
`audit_selenoprotein_end(site_id, gene, reference_gene)`,
`audit_gene_length(site_id, gene)` and `audit_gene_split(site_id, gene_a, gene_b)` take
gene ids and nothing else.
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
span, the strain span with both pads, the selenoprotein span with both pads and the
length or split span with both flanks. A longer window is refused before any gene model
or genome read, naming the gene, the window length and the limit. The length checks
read the ortholog table and the proteins first, because the flank depends on the
protein lengths. The selenoprotein check translates its window in six
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

The pseudogene and selenoprotein checks translate with the standard code. The length
and split checks infer the code of the audited gene from its own coding sequence: the
CDS parts of its gene model, cut from the genome window the check already read and
turned to the gene's strand, are translated under each code `infer_code` knows, and the
first code whose translation equals the site's protein for that gene is used (for a
pair, the first part that one code explains). When no code explains it, the check uses
the standard code and answers `codeInferred: false`. The answer names the code it used.
The reference ortholog's code is not used: it can be another organism, with another
code.

## The length and split checks

`audit_gene_length` reads the gene's `Orthologs` table (`orthologs_of`) and keeps the
protein-coding rows with a length, the longest row per organism (`GroupProfile`). A row
whose site serves no pseudogene flag (`is_pseudo` null, as on the P. chabaudi CB and
P. vivax-like genomes) has an unknown flag: the statistics exclude only a row whose
flag is set, and count the rest by gene type. A record that is not a gene row at all is
a tool error that names the search and the record.

The group can judge a length only with 8 or more organisms, a median of at least 80
residues, an interquartile range at most 0.3 of the median, a median of one copy per
organism and a single-copy member in another organism. A residual group (`OGR`) is not
used as orthology. The gene's own organism must hold no other coding member of the
group: a gene beside a paralog or the other half of a split belongs to
`audit_gene_split`. Otherwise the answer is `UNQUALIFIED`. The gene's protein length is
read against the median of the other organisms of its genus, or the group median when
its genus has fewer than two others (`MIN_RELATIVES`, 2): under 0.7 is `SHORT`, over
1.5 is `LONG`. A `SHORT` call also needs every genus relative at 0.85 of that median or
more, and a `LONG` call every relative at 1.15 of it or less; a gene whose relatives
disagree is `UNQUALIFIED`. `call_length` returns a `Confirmable` call (`SHORT` or
`SPLIT`), which always holds its reference and the lengths the window is sized from, or
a `NotChecked` call (`TYPICAL`, `LONG`, `UNQUALIFIED`).

Only a `Confirmable` call reads the genome. Every other answer is `NOT_CHECKED`, reads
no protein, gene model or genome, and answers `nsInWindow` and `atContigEdge` as null.
A `LONG` gene is not read here: the fusion check explains extra length.

For a `SHORT` gene, the reference is the single-copy member of another organism of the
same species, else of the same genus, else any, nearest the median the gene was read
against, the lower gene id on a tie. The genome window is the gene span with a flank of
12 bases per residue the gene lacks, at least 6,000 and at most 30,000 bases, sized
from the group rows, so a window over the limit is refused before any protein read.
The reference protein is cut into 20-residue windows (step 10) and each is looked for
in the model (identity 0.5 or more), then in the six frames of the window
(`confirm_in_dna`). A window is looked for on the gene's strand first, so a window that
both strands hold counts on the gene's strand; this is the phase 1 behaviour the
thresholds were calibrated with. `GENOME_ENCODES` needs at least three missing windows
on the gene's own strand and at least half of all missing windows; else `ASSEMBLY` when
the window holds an N or the gene lies within `LENGTH_EDGE` (2,000) bases of a contig
end, the contig length read from the genome index; else `ABSENT`. A model that holds
every window answers `NOT_SHORT`.

`audit_gene_split` reads the same group from `gene_a`. The two genes must be distinct,
of one organism, on one strand of one sequence, and the second may start at most
`SPLIT_MAX_GAP` (20,000) bases after the first ends, else the call is refused. Both must
be coding members of the group and next to each other in position order among their
organism's members, else the pair is `UNQUALIFIED`. The pair is a `SPLIT` when each
protein is under 0.85 of the genus median and the two sum to 0.8 to 1.35 of it. A
window of the reference is held by the part with the higher identity, the first on a
tie. `SPLIT_CONFIRMED` needs at least three windows in each part and 60% of all windows
in the two; else `SPLIT_UNCLEAR`. A window that spans the join of the two parts is held
by neither, because a window is matched without gaps.

The verdict rates the prototype measured hold for named products in genomes with under
2% length outliers; the served check answers any gene it is asked about.

The PKA catalytic subunit of P. cynomolgi strain M (PcyM_0736700, 280 residues, a
known missing exon) shows the limit of the group screen. Its `Orthologs` group holds
523 AGC kinases in 63 organisms, with a median of 8 copies per organism, so the length
check answers `UNQUALIFIED` (`groupCopies` 8) and reads no genome. The DNA check of the
same window against the strain B protein (PCYB_074210, 341 residues) answers
`GENOME_ENCODES`, with five windows on the gene strand. The test reads the recorded
wire bodies through the same parsers the served check uses.

Both answers carry `lengthClass`, `ratio` (the summed length over the median it was
read against), `groupMedian`, `groupCopies`, `groupSpread`, `organisms`,
`referenceGene`, `code` and `codeInferred` beside the window `track` and `counts`.

Every input the site cannot give (an unknown id, a reference with no CDS rows, a gene
with no protein, a selenoprotein reference with no selenocysteine, a pair too long to
align, a split pair that is not two neighbours on one strand, a window over the limit,
a gene record with no organism, a record that is not a gene row, a WDK refusal, a
truncated report, a sequence the genome index lacks, a JBrowse error, a site that does
not answer) is a tool error that names it, as `tests/unit/audit/test_audit_tools.py`
and `tests/unit/audit/test_length_tools.py` show.

Every answer is a `CamelModel`, like every other served result, so their keys are
camelCase on the wire (`referenceGene`, `afterModelEnd`, `residueDifferences`).

# What was rejected

**The caller passes the sequences.** A host would have to read a genome window itself,
and the check would answer for DNA nobody can trace back to a site build. Reading the
inputs here keeps one call one verdict about named genes.

**A verdict for an input that is missing.** `MODEL_NOT_FOUND` already means the model
protein was not found in the genome. Reusing it, or adding an `UNKNOWN_GENE` verdict,
would let a typo in a gene id read as a finding about the annotation.

**The reference ortholog's code for the length checks.** The reference is often another
organism, and an ortholog in another clade can read CTG or TGA otherwise, so its code
would mistranslate the audited gene's genome window.
