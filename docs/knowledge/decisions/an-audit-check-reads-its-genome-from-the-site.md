---
type: Decision
title: An audit check reads its genome from the site
description: The served gene-model checks resolve each gene id through the site, read every input themselves from the site the call names (gene records, the ortholog table, the JBrowse genome window and tracks), answer one verdict per call, refuse an input the site cannot give, or a window over the limit, as a tool error and never as a verdict (the intron check's NOT_CHECKED is the one exception), and run at most two checks at a time in worker threads; the evidence tools return what a gene record and an organism record serve, without a verdict.
tags: [audit, tools, jbrowse, wdk]
status: stable
---

# The choice

`audit_pseudogene_call(site_id, strain_gene, reference_gene)`,
`audit_selenoprotein_end(site_id, gene, reference_gene)`,
`audit_gene_length(site_id, gene)` and `audit_gene_split(site_id, gene_a, gene_b)` take
gene ids and nothing else.
`veupathdb_mcp.audit.served` reads what each check needs:

- **Where a gene is**: its own gene record, read by the id given; an id no record names
  goes to `GenesByText` (primary keys only, over every organism its
  `text_search_organism` tree lists, read once per site per process) and takes the one
  gene whose own id, without its `:` qualifier, or whose transcript id is the id
  (`rows_named` in `veupathdb_mcp.audit.gene_ids`; `located` in
  `veupathdb_mcp.audit.served`). How a record read resolves an id, and why no tool
  uploads a gene list, is [a named gene is read by its record](a-named-gene-is-read-by-its-record.md).
  This finds the gene a site serves only under a suffixed id: on QA plasmodb the gene
  record of `PfNF54_100037200` answers 404, and the text search names
  `PfNF54_100037200:pseudogene`, one of the 204 NF54 pseudogenes of 229 served with
  that suffix. An id that holds `*` or a space is refused before the text search; an
  answer over 50 transcripts is refused naming the id; an id that names no gene, or
  several, is refused by name. Every gene-id tool serves `geneIds`, each id given beside
  the gene id it resolved to, reads and serves only the resolved id after that, and its
  answer is invalid when its gene fields are not the resolved ids.
- **Its organism and coding parts**: one gene record read (`gene_model`), attribute
  `organismAbbrev` and table `GeneModelDump`, the CDS rows of the transcript with the
  longest CDS, the lower id on a tie (a row whose `transcript_ids` lists several
  transcripts belongs to each of them). The transcript record declares
  `organismAbbrev` out of its report, so the gene record is the one read that carries
  it. The abbreviation is the JBrowse organism key. A read that needs only the
  abbreviation (the pseudogene check's strain gene, the selenoprotein's gene, the
  organelle check's first coding gene, the missing-gene check's anchor) reads the
  attribute and no table (`gene_organism`).
- **The DNA**: a window of the site's JBrowse genome
  (`veupathdb-py: docs/knowledge/wdk/rest/jbrowse-surface.md`). The reference gene is
  read as its own span. The strain gene is padded by `PSEUDOGENE_PAD` (3,000 bases) on
  both sides, so a coding sequence that runs past the annotated span is still read, then
  turned to its own coding strand. A selenoprotein is padded on both sides by
  `SELENOPROTEIN_PAD` (300 bases) plus three bases per residue of the reference tail
  from its first selenocysteine, so a model that stops at a selenocysteine in the middle
  of the protein still has the whole tail in its window.
- **The proteins**: the longest coding transcript's, the lowest transcript id on an
  exact length tie (`record_proteins`), so every check takes the same transcript
  whatever order the site serves them in.

The pseudogene check reads only a strain gene the site flags as a pseudogene
(`is_pseudo` Yes): a gene flagged coding, or one whose flag the site does not serve, is
refused naming the gene and the flag, so `INTACT` always describes a gene the site calls
a pseudogene. A coding reference gene given as the strain gene is intact by
construction and is refused.

The selenoprotein check aligns the model protein to the reference protein
(`difflib.SequenceMatcher`) and serves `secAligned`: true when the model's last residue,
projected along the last block of identical residues that ends at most `END_SLACK` (3)
residues before it, falls on the residue just before the reference's first
selenocysteine, so a substitution at the model end does not hide a Sec stop. A TGA after a model that ends elsewhere, followed by a short matching
tail, is not a selenocysteine stop. `tailIdentity` is the share of the reference tail
after that selenocysteine (to its stop) that the genome encodes after the model end,
compared residue by residue up to the first stop the genome reads there that the tail
does not hold. `STOPS_AT_SEC` needs `secAligned`, the TGA and `tailIdentity` of
`TAIL_IDENTITY` (0.8) or more, so a tail may differ in one residue of five across
species; the recorded T. gondii GT1 SelK tail is 1.0 and aligned. A later
selenocysteine in the reference tail is compared as a stop, since the genome frame
reads its TGA as one; a protein with two selenocysteines still matches.

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
read the ortholog table first, because the flank depends on the protein lengths it
lists, and read the proteins only for a window under the limit. The selenoprotein check translates its window in six
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

The pseudogene and selenoprotein checks, and the anatomy's `dnaCheck`, translate with
the standard code, and their descriptions say so. The length
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
members with a protein length, the longest per organism (`GroupProfile`); a member the
table gives no length counts as not coding. The gene itself, which the table does not
list, counts by its own row: a row whose site serves no pseudogene flag (`is_pseudo`
null, as on the P. chabaudi CB and P. vivax-like genomes) has an unknown flag, and only
a set flag or a gene type that is not protein coding excludes it. A split partner
counts only when the table lists it.

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
be coding members of the group and the only two coding members of it in their organism,
else the pair is `UNQUALIFIED`: a gene in three pieces would otherwise answer two
overlapping pairs. The pair is a `SPLIT` when each
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
and `tests/unit/audit/test_length_tools.py` show. The label comes from the error the
client raises: a WDK error caused by an HTTP status, or a `JBrowseError` with its
`upstream_status`, reads "<site> answered <status> to the audit reads: <detail>"; one
caused by a timeout or a failed connection reads "<site> did not answer the audit
reads"; any other refusal keeps its own detail. A report served short of its total is
a `DataParsingError` naming the search and both counts, a data fact and not an outage,
so a caller that retries outages does not retry it.

Every answer is a `CamelModel`, like every other served result, so their keys are
camelCase on the wire (`referenceGene`, `afterModelEnd`, `residueDifferences`).

## Where a check reads a genome's genes

`GenesByLocation`, the region search, holds only some genomes of a site in its
`organismSinglePick` vocabulary, and the site answers 422 for any other organism. On QA
toxodb it holds the 8 chromosome-level genomes (Besnoitia besnoiti Bb-Ger1, Eimeria
tenella Houghton 2021, Neospora caninum Liverpool and Liverpool 2019, T. gondii GT1,
ME49, RH-88 and VEG), so no scaffold genome has a region read. On QA plasmodb it holds
16 P. falciparum strains and lacks NF54, 7G8 2019, NF135 and NF166.
`GenesBySequenceSourceId` answered 500 on QA toxodb. The audit has no region reader:
the missing-gene, organelle, genome pseudogene-call and gene-fusion checks read a whole
genome with one `GenesByTaxon` report (`genome_answer`, `genes_of_genome`), which takes
every genome of the site, is refused when it is truncated, and is parsed into gene rows
in a worker thread. The fusion and missing-gene checks walk a contig outward from a gene
with one rule (`contig_sides`).

The genome-priority check and the genome provenance read the site's organism records
with one report, `organism_report` (the `organism` record type's `GenomeDataTypes`
search, no parameters), each for its own attributes. The gene-evidence check and the
expression summary read the gene record type once per site in a process
(`gene_record_type`, a `SiteCache` of the parsed `GeneRecordType`): the evidence check
reads its tables and the summary its key columns. The anatomy, the intron check and
`gene_model` read a gene's `GeneModelDump` record through one parser (`model_record`).

Of the readers no served check calls, `rate_with_bounds` is kept for PathFinder's audit
pass, which states a rate over the calls a later check confirms; the region reader and
`covered` (the peptides over a residue span) had no planned consumer and are gone.

## The strain-model check

The strain-model check reads two genes of one species, in two genomes and one ortholog
group, with their proteins and the reference's group. It lists the runs of 20-residue
windows (step 10) each protein holds under 0.35 in the other, two windows or more, with
low-complexity and repeated windows left out. It reads the strain's genome only when
the strain lost a run. It does not read it when the group is residual (OGR is not
orthology, so the pair is unqualified), or when another member of the group in the
strain's organism, coding or not, lies on the same sequence within the read window,
because that copy can answer for the lost windows. A copy the group does not list is
not seen: a pseudogene, which the Orthologs table omits, or an unannotated copy. The
read uses the length check's window and flank (12 bases per residue of length
difference, 6 to 30 kb) and confirms the lost segment with the length check, against
the two proteins the check already read. A side is judged only when the strain's genome
encodes the lost segment. The strain is short when the reference is within 10% of its
relatives' median and the shorter strain is not. The reference is long when the strain
is within 10% and the longer reference is not: the strain's genome encodes a segment
the relatives lack, as a model that starts too early does. The relatives are the
organisms of the other species of the reference's genus, else of the other genera,
each by its longest member, leaving out the organisms of both the reference and the
strain (`relatives_of(reference, model, rows)`, the one rule `relatives_median` also
serves), and the answer lists them with their median (`relatives.median`). A pair whose
group label is neither an `OG` nor an `OGR` group (an `N/A` label) is refused. A group with more than one copy
per organism, or with fewer than two relatives, gives no side. A strain longer than its
reference is never called short; against the prototype's arbitration, which had no
such guard, this turns 10 of 628 strain-short cases into unclear.

## The missing-gene check

`audit_missing_gene(site_id, example_gene, absent_organism)` asks whether a genome holds
a gene its annotation lacks. It reads the example's row and protein (a gene the site
serves no protein for, or a protein under 40 residues, is refused), then the absent
genome with one `GenesByTaxon` report, because `GenesByLocation` cannot read a scaffold
genome. When the absent genome annotates genes of the example's `OG` group anywhere,
the syntenic locus included, the answer is `ANNOTATED_IN_GENOME`: `annotatedMembers` names each with its sequence
and start, and no other genome or DNA is read, so a translocated copy is not read as a
missing gene. `annotatedMembers` is empty when the group has no member there, and null
when the example's group is not an `OG` group. Otherwise the example's own genome is
read with a second report. The walk takes up to `ANCHOR_REACH` (6) genes on each side of the example on
its contig and stops on each side at the first gene whose `OG` ortholog group has
exactly one gene in the absent genome. A residual (`OGR`) group and an `N/A` label
never anchor; pseudogene rows carry `N/A (orthology not determined for pseudogenes)`,
so a pseudogene never anchors. The two anchors must be two genes on one contig with at
most `ANCHOR_MAX_SPAN` (60,000) bases between them, else the answer is `NO_SYNTENY` and
no genome is read. The genetic code is inferred from the example gene's own CDS and
protein (the standard code, with `codeInferred: false`, when no code explains it). The
DNA between the anchors, padded by `MISSING_PAD` (3,000) bases, is at most 66,001
bases, under the window limit. The example protein is cut into 20-residue windows
(step 10); each of the six frames is matched alone, and a window found at identity 0.5
or more adds its 60 bases to the span. `IN_DNA_UNANNOTATED` needs 60% of the windows
and no model of the absent genome over the span; it says the DNA holds the protein's
sequence, not that one intact reading frame holds it. `IN_DNA_OTHER_MODEL` names the
overlapping models with their `pseudo` flag, because a gene's `Orthologs` table omits a
pseudogene, so a genome can look absent from the table while the span holds a
pseudogene model. Below 60%, more than 100 Ns is `GAP`, 35% or more is `PARTIAL`, and
less is `NOT_IN_DNA`. `stops` lists the stop codons inside the stretch that the found
windows cover in the frame that holds the most of them, as residue positions of the
example protein, and `intactFrame` is true only when every found window lies in one
frame and that frame has no stop over the whole protein. A `NO_SYNTENY` or
`ANNOTATED_IN_GENOME` answer serves no genome fact: `anchors`, `located`,
`overlapping`, `stops` and `code` are null and `codeInferred` is false, as in every
other audit that reads no genome, and only those verdicts have them so. The TGARI_257090
recording holds no GT1 gene of its group (OG8_0003979). `openFrame` is the stop-free stretch over the span,
read to its stop codon or the window end, with the most residues identical to the
example protein. The NAC domain protein of T. gondii ARI (TGARI_257090, 359 residues)
answers `IN_DNA_UNANNOTATED` in GT1: 34 of 34 windows between TGGT1_257070 and
TGGT1_257100 on TGGT1_chrVIIb (span 4156680-4157729, no Ns, no model over the span),
one stop at residue 163, and the longest stop-free stretch carries 196 of the 359
residues.

## The organelle join check

`audit_organelle_gene(site_id, organism, sequence_id, reference_gene)` takes the
organism's full name and the contig. The reader locates the reference gene and reads its
protein; it then reads the organism's genes (`genes_of_genome`, the `GenesByTaxon`
report), takes the first protein-coding, non-pseudogene gene on the named sequence and
reads its gene record for the JBrowse key (`organismAbbrev`). A sequence with no such
gene of the organism is a tool error that names both. `GenesByLocation` is not used: it
cannot read NF54 or 7G8 2019, the genomes this check is for. The reader then reads the
contig length from the genome index and refuses a contig over
`AUDIT_MAX_WINDOW_BASES` before any genome read. It infers the code from the reference
gene's own CDS and protein (the standard code with `codeInferred: false` when no code
explains it) and reads the whole contig. The end overlap is the longest k of at least
`ORGANELLE_MIN_OVERLAP` (20) and at most half the contig for which the last k and the
first k bases agree at `ORGANELLE_OVERLAP_AGREEMENT` (99%) of positions or more (N
agrees with nothing), counted for every k at once by FFT cross-correlation of the
per-base indicators, and whose start copy does not repeat a unit of
`ORGANELLE_SHORT_PERIOD` (6) bases or fewer (a homopolymer or a short tandem run at both
ends is not an overlap; a real direct repeat at both ends cannot be told from an
assembly overlap and is read as one). It is cut once from the end and served as
`overlapBases` and `overlapMismatches`. A reference whose protein needs more than half
the circle (the contig minus the overlap) in coding bases is a tool error naming the
gene, the contig and the circle length: a turn by half cannot place it whole. The
contig is then read as a circle turned by half its length. Each open frame (stop to
stop, six frames) is scored by the residues it shares with the reference protein: the
sum of the `difflib.SequenceMatcher` matching blocks (no autojunk) of at least
`ORGANELLE_WORD` (4) residues, longest frames first. `INTACT_ON_THE_LINE` needs a frame
of the contig as stored that holds 95% of the reference residues; `SPLIT_AT_JOIN` needs
one only in the circle; else `NOT_FOUND`, which a frameshift in the assembly or a
reference of another species also gives. On QA plasmodb, PF3D7_MIT02300 (cytochrome b,
376 aa) reads the standard code (20 ATA codons read as isoleucine, no TGA) and answers:
3D7 Pf3D7_MIT_v3 `INTACT_ON_THE_LINE` 376/376; NF54 CM019798.1 `SPLIT_AT_JOIN` 274/376,
ends overlapping by 87 bases; 7G8 2019 CM019769.1 `SPLIT_AT_JOIN` 248/376, overlap 127;
7G8 Pf7G8_MT `SPLIT_AT_JOIN` 272/376, overlap 127 with one differing base (the contig's
last base); SN01 PfSN01_MT `NOT_FOUND` 291/291, overlap 127, whose assembly breaks the
frame.

## The genome priority

`audit_genome_priority` reads one report per site: the organism report for
`organism_full`, `busco_protein`, `busco_genome` and `busco_lineage_dataset`. A BUSCO
score is served as text (`C:  93.0%[S:  92.5%,D:   0.5%],F:   0.1%,M:   6.9%,n:1378`);
the complete, fragmented and missing shares and the gene count are read from it, and
other text is refused. The gap is the genome's complete share minus the protein's, in
percentage points: conserved genes the genome holds but the annotation lacks. Genomes
are ranked largest gap first, the organism name on a tie, and served as `genomes`
beside `siteId`. An organism the site scores
on one side only (an unannotated genome serves `busco_protein` as null) is left out,
with or without a lineage; a lineage is required only of an organism with both scores.
On plasmodb NF135.C10 has a gap of 5.4 (protein 93.0, genome 98.4) and 3D7 of -0.8; on
toxodb (lineage coccidia_odb12, n:461) 38 of 42 organisms carry both scores. The scores
are genome-level only: the sites do not serve which genes BUSCO found missing, so the
priority says where to run the gene-level checks, not which gene to check. The tool
reads no genome, so it has no window limit and no audit budget.

## The anatomy of a pseudogene call

`audit_pseudogene_anatomy(site_id, strain_gene, reference_gene)` states where a
pseudogene's model breaks and what the genome holds there, and draws no conclusion. A
pseudogene's `GeneModelDump` serves `Exon` and `Intron` rows and no `CDS` row, so its
segments are the `Exon` rows of the transcript with the largest summed exon length
(`longest_transcript`, the rule `coding_parts` applies to `CDS` rows); the reference's
segment count uses the same rule. Each junction gives the gap between two segments, the
gap modulo 3, the longest single-base run of the genome with a base within 5 positions
of the gap's first or last base, inside or outside the gap, and the Ns within 100
positions of those bases; the gene gives its distance to each contig end and its Ns.
The contig length is the genome index's, and `dnaCheck` is the pseudogene check of the
genome window against the reference's longest-CDS transcript, so for a reference with
several transcripts `referenceSegments` and `dnaCheck` can describe two transcripts. The anatomy reads each gene record once (the reference record gives the
`dnaCheck` reference model and its segment count, the strain record its abbreviation
and segments) and the strain window once: it is the pseudogene check's window, the gene
span padded by 3,000 bases, so a segment outside it is refused before any genome read.
The shared `pseudogene_pair` and `pseudogene_dna` apply the pseudogene check's
refusals. Both computations run in the
audit worker slot. A site serves a pseudogene's gene id with the suffix `:pseudogene`
(`PfNF54_100037200:pseudogene`); the plain id resolves to it.

## A genome's pseudogene calls

`audit_genome_pseudogene_calls(site_id, organism, reference_organism)` lists a
genome's pseudogene calls and reads no DNA: two `GenesByTaxon` reports through
`genes_of_genome`. Its name follows the genome-level tools (`audit_genome_priority`,
`audit_genome_provenance`) and keeps it apart from the one-gene
`audit_pseudogene_call`. Each report is a whole-genome report, so the tool declares the
audit budget, and the pairing runs in the audit worker slot. A pseudogene is a row
whose `is_pseudo` is true; a coding reference gene is a row whose `is_pseudo` is false,
that `is_coding` calls protein-coding and whose group is an `OG` group that is not
residual (`is_orthology_group`); on the recorded 3D7 report that is the same 5,318 genes
as the earlier rule (flag false, group starting with `OG`). A row whose flag the
site does not serve is neither, and the answer counts those rows for both genomes
(`unflagged`, `referenceUnflagged`); `noGeneFlagged` is true when the organism has
genes and the site flags none of them, so an unflagged genome does not read as one with
no pseudogene. A pseudogene with an orthology group (`OG`, not the residual `OGR`) pairs
only when one coding reference gene holds that group; one without a group pairs only
when one coding reference gene holds the identical product. A product that holds any
word of `FAMILY_WORDS` as a lowercase substring does not pair, on either side:
gene-family names, hypothetical and unknown-function products, and every other product
that holds a listed word, such as "histone H3 variant" ("var"). The answer counts every
pseudogene of the organism, lists the paired ones with the basis of each pair
(`ORTHOLOG_GROUP` or `PRODUCT`), lists the others in `unpairedGenes` with their reason
(`FAMILY_WORD` with the word, `NO_REFERENCE`, `SEVERAL_REFERENCES`), and counts them by
reason. The description lists every word. It
draws no conclusion about any call; `rate_with_bounds` states a rate over the calls a
later check confirms, with its Wilson 95% interval (the upper bound is one minus the
lower bound of the complement, so the interval stays in [0, 1]), and its floor and
ceiling over every call when some could not be checked.

## The evidence a check is judged by

`audit_gene_evidence(site_id, gene)` and `audit_genome_provenance(site_id, organism)`
return what the site serves, without a verdict. The first reads the gene record type's
table list (`GET /record-types/gene`, once per site per process) and one gene record
with its `organismAbbrev` and the tables the record type declares among
`GeneTranscripts`, `PdbSimilarities`, `MassSpecDownload`, `AlphaFoldLinkouts`,
`GeneLinkouts`, `Seqedits`, `UserComments`, `PubMed`, `Notes` and the phenotype
screens: the data tables the gene page draws its phenotype graphs from
(`EdaPhenotypeGraphsDataTable`, `PhenotypeScoreGraphsDataTable`,
`PhenotypeGraphsDataTable`, `CrisprPhenotypeGraphsDataTable`) and every other table
whose name holds "phenotype" and not "graph", "dataset" or "image". A table is the
organism's own when its name starts with the gene's `organismAbbrev` and "_" (an
abbreviation may hold "_", as `aaegLVP_AGWG`); own tables are served in `phenotypes`
with their rows, empty included. A table named for another organism (a lowercase
abbreviation prefix that is not the gene's) answers empty and is not served. A table
named for no organism (`EdaPhenotypeGraphsDataTable`, `PhenotypeScore`,
`RodMalPhenotype`, `CGD_CuratedPhenotypes`, `PhenotypeMagnaporthe`, ...) is offered on
every organism of the site and is served apart in `unprefixedTables`, never as a screen
of the gene's organism. An own table with no row does not mean the screen has no
result: the P. falciparum piggyBac screen's table answers no row, while its mutagenesis
index and mutant fitness scores are served in `EdaPhenotypeGraphsDataTable` under its
`dataset_id`. A table the record type does not declare is never asked, and `unserved`
names it, a table in `tableErrors` and a table the record leaves out.
`PdbSimilarities` serves no residue positions and at most 20 rows (chains) per
transcript, and its "% of VEuPathDB protein covered" is 0 for near-identical hits.
Peptide positions are on their own transcript's protein (ELVADMR at 195-201 on
LmjF.35.3010.1 and 87-93 on LmjF.35.3010.2). The second reads the
organism report once and picks the record whose `organism_full` is the name given;
`genomeVersion` holds the assembly accession and version (or a date), a blank
annotation source is null, and build 0 is null; `recordId`, `referenceStrain` and
`ncbiTaxon` are served as the record states them. An organism the report does not hold
is a tool error.

## The intron support check

`audit_intron_support(site_id, gene)` judges only the transcript with the longest CDS
(the one `coding_parts` picks) and serves its id and how many other transcripts the gene
has; their introns are not judged. It reads the gene's row, one `GeneModelDump` record,
and every tabix junction track of the organism's rnaseqJunctions list over the gene +-
200 bases, with one tabix reader per JBrowse client, so a track's index is read once
while the client lives; a track that does not index the gene's sequence is named in
`tracksRefused`, and when no track indexes it the check is `NOT_CHECKED`, never
`NOT_EXPRESSED`, with every refusal in `tracksRefused`. `tracksRefused` is null when no
track was read. A gene with no CDS or intron, an organism with no junction track and an
unindexed sequence are `NOT_CHECKED` answers rather than tool errors, the one exception
to the refusal rule above: the answer names the transcript it would have judged.
`NOT_CHECKED` serves `introns` and `unread` null, and `NOT_EXPRESSED` serves `unread`
null, since no intron was judged.
Junctions with no strand are set aside and counted (`unstrandedIgnored`); only a gene
whose every junction has no strand is `NOT_CHECKED`. The expression gate has two forms,
and `bestJunctionReads` is what it measured. When an annotated intron has a read, the
gene is expressed when its best annotated intron has 50 reads or more, exactly as the
prototype screen; a novel junction never opens this gate. When every annotated intron is
unread, the gene is expressed when a Strong Evidence junction on its strand lying wholly
inside it has 50 reads or more; this second gate extends the prototype, which skipped
such genes. 20 reads is only the bar a replacing junction must reach. Every unread
annotated intron of 20 bases or more is judged on its own and in stages
([a named gene is read by its record](a-named-gene-is-read-by-its-record.md)):
`SHIFTED` by one Strong Evidence junction of 20 reads or more within 30 bases at both
ends, `MISSING_EXON` by a chain of such junctions each starting under 2000 bases after
the last, `REPLACED` by one inside the gene that overlaps it, ends more than 30 bases
from it and holds a quarter of the median reads of the gene's read introns; a genomic
peptide split across it supports it; `NONCANONICAL` when its motif is neither `GT..AG`
nor `GC..AG` (a motif with a base other than A, C, G or T is an assembly gap and is not
read); `RETAINED` when its median depth is a quarter of the exons' median, 0.9 of its
bases are covered and every other intron has 20 reads; `UNEXPLAINED` otherwise. The verdict takes the first of
`UNEXPLAINED`, `NONCANONICAL`, `RETAINED`, `MISSING_EXON`, `REPLACED` and `SHIFTED`.
Only when no unread intron is `UNEXPLAINED` are the protein and the genome (gene +-
3000) read and all of them applied together, a junction outcome by cutting its
junctions out and a kept intron by reading it as exon; the corrected CDS is served in
ascending genome order with its stop codon. The corrected exons are served beside it, the
same composition merged, and a reading frame that runs past the last exon on the gene's
strand lengthens that exon to its stop codon, because a CDS is part of its transcript; a
separate extension field was rejected, since each host would merge it again
(`tests/unit/audit/test_introns_correction.py`). When the protein or the genome window
cannot be read, or the window misses the transcript, the judgement stays and
`correctionReason` says why, with the corrected fields, code and orthologs null. The
ortholog count names, per species other than the gene's own and in the table's order,
the reference-strain member and the member nearest the gene's protein length, up to 16,
keeps the closest copy per species (3-mer Jaccard, 8 species) and counts the orthologs
whose own 20-residue windows are found only in the corrected or only in the annotated
protein, with how many were named and read; a group that is not an `OG` group (`OGR` or
an `N/A` label), or a failed ortholog read, serves no count and the reason, and never
drops the correction. On QA, PcyM_0736700 answers `UNSUPPORTED_MISSING_EXON`: its
unread intron 1381746-1382305 is replaced by junctions of 1436 and 1686 reads, the
corrected CDS parts are [124,158,185,160,399] (341 aa, served 280) and
`bestJunctionReads` is 1970. Afu2g18040 answers `UNSUPPORTED_SHIFTED`: its unread intron
4793693-4793790 is replaced by 4793713-4793786 (1226 reads), the corrected protein has
459 aa (served 451) and `bestJunctionReads` is 1349. The check reads the junctions with
the client's tabix reader, released with veupathdb-py 0.1.0b17, and the depth with its
bigWig reader, released with 0.1.0b19.

## The gene-fusion check

`audit_gene_fusion(site_id, gene)` classes the gene as the length check does and reads
more only for a `LONG` gene; every other class answers `fusion: null` with no protein
or genome read. For a `LONG` gene it reads the proteins of the gene and of the closest
single-copy ortholog (a gene with no protein is refused before any genome read), the
reference's genome with one `GenesByTaxon` report, and the proteins of up to
`NEIGHBOURS_EACH_SIDE` (3) genes on each side of the reference on its sequence, in
position order. The extra runs are the strain check's `missing_runs` of the gene's
protein against the reference's. Each 20-residue window of a run (step 10) counts for
the neighbour that holds it at the highest identity, when that is 0.5 or more; a
neighbour with no protein holds no window. `EXTRA_MATCHES_NEIGHBOUR` needs the top
neighbour to hold at least 3 windows and 40% of them, else `EXTRA_UNEXPLAINED`; `NO_EXTRA` has no
extra window. A window that the reference holds at 0.35 or more, a low-complexity
window and a window repeated elsewhere in the protein are not extra, so a tandem
duplicate or a repeat expansion answers `NO_EXTRA`. Only a match names a `partner`, with
its group and product; an unexplained answer names the neighbour with the most windows
as `closestNeighbour`, as the prototype named its top neighbour, under a name that does
not read as a fusion. `neighbourWindows` counts the windows of whichever is named, and
`product` is the gene's own, so a product that names two proteins is in the answer
without a second read. Only a match whose partner is in an `OG` group reads the gene's
own genome:
`partnerCopies` lists the genes within 3 of the gene on its sequence in the partner's
group, a separate model of that neighbour beside the gene. The verdict states a protein
fact: the gene's extra residues match a neighbour's protein. It reads no DNA and no RNA,
so it says nothing of how the model was built; that is for a check that reads the
genome or the junctions. The check reads no DNA
window, so the window limit does not apply; it declares the audit budget for its two
whole-genome reports and runs the window match in a worker thread. On QA plasmodb
AK88_02763 (P. fragile nilgiri, 26S protease regulatory subunit 8, 1095 residues,
2.583 of its genus median) against PCOAH_00051830 holds 66 extra windows, 56 of them in
PCOAH_00051820, and P. fragile has no model of that neighbour's group beside it. In
both genomes the two genes before the pair and the three after it are in the same
groups; only the partner's group has no P. fragile gene there.

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

**Adding the `:pseudogene` suffix to an id the site does not find.** It encodes one
site's naming in the library and would answer for an id that names another gene with
that suffix. The site's text search over gene ids and aliases is the site's own answer,
and a word that names several genes is refused.

**Any word match of the text search, aliases included.** A word of an alias or a
wildcard match names genes the id does not name; only a gene whose own id or transcript
id is the id is taken, so the search reads primary keys only. The gene record read
already resolves the site's aliases and previous ids.
