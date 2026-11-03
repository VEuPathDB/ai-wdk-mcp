---
type: Decision
title: A short model names the frameshift that cut it
description: The length check records the reading frame of each window it places in the DNA; when the missing windows continue close by in another frame it answers FRAMESHIFT, naming the span, both frames, the repeat that holds the change, the same stretch in the reference strain and what the site's variant calls say of the strain's reads, rather than GENOME_ENCODES, which now means the same frame.
tags: [audit, length, frameshift, assembly, variants]
status: stable
---

# The choice

`confirm_in_dna` places each `model` and `genome_same_strand` window in the three frames
of the gene's strand (`WindowHit`: its base on that strand, its identity there and in the
model). Equal scores go to the place nearest the last window's diagonal, so a window of
one repeated residue stays on its line. `locate_frameshifts` groups the placed windows
by diagonal (the base minus three bases per residue), keeps groups of
`MIN_BLOCK_WINDOWS` (2) or more, and reads a frame change between two neighbouring groups
when all of these hold:

- the diagonals differ by no multiple of 3 and by at most `MAX_SHIFT_BASES` (20), so an
  intron or a larger gap in the DNA is not a frame change;
- at most `MAX_GAP_WINDOWS` (3) windows lie between them;
- within `BOUNDARY_WINDOWS` (2) of the change, a window matches the DNA better than it
  matches the model. A change the model itself spans, such as a short intron, has no such
  window. Testing the state of the window alone would miss the served example: past the
  change, a reference `KQKQKQ` still matches the model's `KTKTKT` at 0.5, so those
  windows read as `model` and the model does not hold them.

A change turns `GENOME_ENCODES` into `FRAMESHIFT`. Only that verdict changes:
the same counts that fall short of `GENOME_ENCODES` still answer `ASSEMBLY` or `ABSENT`,
and two model parts remain a split question.

`frameshifts` lists each change with its source (site, organism, seqid), its genome span,
the frame on each side, `shift` (the bases the genome holds beyond the reference's
spacing, so an extra base is +1) and the residues of the reference protein. The span comes
from the residue at which one frame stops explaining the reference and the other starts:
every tied cut is kept, and in a run both frames read alike the span covers the run.

`run` is the longest homopolymer of `MIN_RUN_BASES` (6) or more that touches the span,
else the longest tandem repeat of up to `MAX_REPEAT_UNIT` (6) bases and
`MIN_REPEAT_COPIES` (3) copies, spelled on the gene's strand, else null.

## The reference strain

The same stretch is read in one gene named by the check: the strain check's reference, or
for the length check the one member of the group in another genome of the species that
the site marks as its reference strain. The length check's own reference is the member
nearest the median, so it can be any strain. The stretch is found between the
`FLANK_BASES` (15) on each side of the run, in that gene's span plus `REFERENCE_PAD`
(300), the nearest pair of flanks when one repeats. A residue position is not used: the
length check's reference protein can belong to another gene than the one read here.
Flanks not found give `referenceRun: null`. Nothing is compared for a genome with no such
reference.

## The variant calls

Over `referenceRun` plus one base on each side, for the anchor base of an indel, the check
runs `VariantsByLocation` (record type `variation`) for the reference's organism, reads
each variant's `VariantStrains` table and `indel_ref_allele`, and answers for the audited
strain's sample. Parameters it does not state take their initial value under the organism,
because `eda_sample_table_suffix` hangs on the organism. `INDEL_CALLED` needs a sample row
that is not genotype `0` or `No call`, with an allele of another length than
`indel_ref_allele`. `NO_INDEL_CALLED`, `NO_VARIANT_CALLED`, `NOT_COVERED` (each row says
`No call`) and `NOT_SAMPLED` (no row names the sample) are the others. A sample matches a
genome by its abbreviation less the four-letter species prefix, against the sample name up
to its first `_`, ignoring case: `pfalDd2` is `DD2_WTSI`, `pfalKE01` is `KE01`. A site that
answers 404 for the search or 422 for the organism gives `variantCalls: null`.

`determinable` says whether the answer can tell. The served calls hold almost no indel
inside a run of `MIN_UNCALLED_HOMOPOLYMER` (7) or more identical bases, although such runs
vary often among field isolates: on QA plasmodb, of the 240 frameshift sites in such a run
whose strain is a sequenced sample, none holds an indel call in the strain's reads within
35 bases, against 2 of 51 outside such runs. So over such a run a missing call
is not determinable, and only outside homopolymers does a missing call say the reads
carry no change. A strain with no reads there is not determinable either.

`VariantsByLocation` is an expensive search, so each read holds the search line. The check
reads it only for a `FRAMESHIFT`, and only over the run.

# What was rejected

**A frame label on `GENOME_ENCODES`.** Every host would have to read a second field to
learn that the model is not what is wrong, and a host that reads only the verdict would go
on reporting an annotation truncation.

**The longest repeat of any kind.** The served example has 29 A beside eleven copies of
`AAAAC`. The tandem repeat is longer and touches the span, but the base count that differs
between the strains is in the homopolymer, where long-read assemblies miscount.

**A table of samples per genome.** It would hold one species of one site and go stale when
the site adds a sample. The served sample names follow the genome names; a name that does
not follow answers `NOT_SAMPLED`, which says nothing either way.

**Failing the whole check when the variant search has no calls for the organism.** The
frameshift stands on the DNA alone. Any other refusal is a tool error, as for every input
of an audit.
