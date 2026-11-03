---
type: Decision
title: A short model names the frameshift that cut it
description: The length check reads what the windows and DNA show, in order - an N between the parts is ASSEMBLY, a part in the model's open frame is GENOME_ENCODES, a part in another frame is FRAMESHIFT when one miscount fits and no splice pair sits at the change, else OTHER_FRAME - and it states the run, the reference run and the served variant records as facts, drawing no cause from them.
tags: [audit, length, frameshift, assembly, variants]
status: stable
---

# The choice

`confirm_in_dna` places each `model` and `genome_same_strand` window in the three frames of the
gene's strand (`WindowHit`: its base on that strand, its identity there and in the model). A window
that matches the DNA better than the model is beyond the model, whatever its state: past a change, a
reference `KQKQKQ` still matches the model's `KTKTKT` at 0.5. Groups of `MIN_BLOCK_WINDOWS` (2) or more
windows on one diagonal (the base minus three bases per residue) are the parts.

`check_length` answers a short model in this order:

- **A. An N in the stretch of a jump is `ASSEMBLY`**, in the same frame or not. The stretch is the DNA
  from a placed window to the next where either is beyond the model and the two are not read across:
  they lie on different diagonals, or a window between them could not be placed. An N with windows
  placed on one diagonal through it is a base of known length: not `ASSEMBLY`, and stated in `nsInPart`.
- **B. A part in the model's own frame, with the frame open from the model to it, is
  `GENOME_ENCODES`.** Two windows beyond the model must share the frame of the window beside them,
  with no stop from one to the other, and on both sides when the model lies on both. B reads only the
  windows beside the model: a frame change further out is stated in `frameChanges`, and the verdict
  stays, because the near part really is open. `partOpen` reads further, across every placed window
  beyond the model: it is true when all of them share the model's frame with no stop and no N from the
  model to them. `partStop` names the first stop. `readingFrameHolds` needs `partOpen`, so a stop past
  the near part or one window in another frame is never read as a whole open part.
- **C. Anything else on another diagonal or past a stop is one of two.** Only a change that does not
  keep the frame can make it `FRAMESHIFT`.
  - **`FRAMESHIFT`**: a change with at most `MAX_GAP_WINDOWS` (3) steps of
    `STEP` residues between the parts (so at most 2 windows between them), a run at it whose unit explains
    the shift as 1 or 2 copies, and no splice pair at it (`runExplainsShift`). The shift limit is the error
    the verdict names: an assembly miscounts a run by a unit or two. A real slip outside a repeat reads
    `OTHER_FRAME`. Where the model lies does not decide it: real
    projected models splice around a slip or start after it. `modelGoesOn` states which, and no
    answer says the slip stopped the model. Run counts are stated and never filtered on.
  - **`OTHER_FRAME`**: everything else, such as a shift of 4, 5, 7 or 10 bases, a splice pair at the
    change, or a stop in the model's frame before the part. The part is encoded, and the cause is not
    shown.

The splice pair is read at the change: a donor at the left part's end and an acceptor at the right
part's start, each within `SPLICE_SLACK` (6) bases for residues that match by chance, from
`CANONICAL_MOTIFS`, at least `MIN_INTRON` apart, with a length that leaves the later frame. A pair
anywhere inside the stretch is not read: chance pairs there lost real one-base changes once the
reference diverged.

`frameChanges` lists every jump between diagonals of the whole track, whatever its size, under every verdict, a jump
with `runExplainsShift` first and then in gene order, up to `MAX_FRAME_CHANGES` (3), so the reads stay bounded and a
`FRAMESHIFT` always rests on a listed jump. `unlistedChanges` holds the jumps past the cap, with
their shifts and pairs and with no run in the reference or variant calls read. `keepsFrame` states a `shift` that is a
multiple of 3. `everyChangeAtASplicePair` and `readingFrameHolds` read both lists. Each entry states genome span, frames (the genome position of a codon's first base, less
one, modulo 3), `shift`, the residues of the reference protein, `run`, `splicePair` and `modelGoesOn`. `run` is the
longest homopolymer of `MIN_RUN_BASES` (6) or more that touches the span, else the longest tandem
repeat of up to `MAX_REPEAT_UNIT` (6) bases and `MIN_REPEAT_COPIES` (3) copies, spelled on the gene's
strand, whose unit explains the shift. N is not a repeated base.

The recorded PKA catalytic subunit of P. cynomolgi strain M reads `OTHER_FRAME`, because its missing
exon lies past an intron: the first change has a shift of 141 and names `GT..AG`, so a reader can see
the missed exon. A short model is short whatever frame the rest is in, so a strain's side is
judged from its relatives under `GENOME_ENCODES`, `FRAMESHIFT` and `OTHER_FRAME` alike.

`every_change_at_a_splice_pair` is true when there is a change and each has a pair at it. It is not proof
of an exon. On random sequence, for a stretch of 30 to 300 bases at `SPLICE_SLACK` (6) with 40,000
draws, a pair sits at one change by chance 9.3% of the time at 80% A+T and 24% at 60% A+T. Taking
changes as independent, that is 0.87% and 5.8% at two changes, and 0.08% and 1.4% at three.

## The reference strain

The same stretch is read in one gene named by the check: the strain check's reference, or for the
length check the one member of the group in another genome of the species that the site marks as its
reference strain. The stretch is found between flanks in that gene's span plus `REFERENCE_PAD` (300).
A flank must occur in exactly one place: it starts at 15 bases and widens to 30, 60 and 120 while it
occurs more than once. `referenceUnread` says why when none is placed: `FLANK_SHORT`, `FLANK_MISSING`,
`FLANK_REPEATED`, `EMPTY_SPAN`, `MODEL_UNREAD` or `WINDOW_TOO_LONG`. `countsMatchShift` states whether
the run less the reference run equals the shift. It can be false: flanks in different copies of a
repeat gave 82 against 8, and that must read as a mismatch.

## The variant calls

Only a jump with `runExplainsShift` reads the reference strain and the variant calls, and the search
details are read once for a check. A plain intron with no run reads nothing further: 62 of 86 real jumps.
Over `referenceRun` plus one base on each side, the check runs `VariantsByLocation` (record type
`variation`) for the reference's organism and reads each variant's `variant_type`, `indel_ref_allele`,
`indel_frame_effect` and `VariantStrains` table. Parameters it does not state take their initial value
under the organism; `sequenceId`, whose initial value is a placeholder, is always replaced.

`variantCalls.sites` states each record as served, with the genotype, allele, depth and read frequency
of each sample whose name matches the strain (the first word of each name, split at any character that
is not a letter or a digit, ignoring case, against the abbreviation less its species prefix). No value
is interpreted. `callsSayLittle` is true over a homopolymer of `MIN_UNCALLED_HOMOPOLYMER` (7) or more
bases with no indel record: on QA plasmodb, of the 240 frameshift sites in such a run whose strain is a
sequenced sample, none holds an indel call in the strain's reads within 35 bases, against 2 of 51
outside such runs. `variantsUnread` gives `NO_REFERENCE_RUN`, `NO_VARIANT_SEARCH` (404), `SEARCH_REFUSED`
(422, unread and not evidence) or `TOO_MANY_VARIANTS` (over 50), and the finding stands on the DNA. Any
other refusal is a tool error. `VariantsByLocation` holds the search line, and is read only for a change.

# What was rejected

**A shift of 1 or 2 bases with no run as `FRAMESHIFT`.** A true GT..AG intron with a length near a
multiple of 3 fits a small shift when the pair is missed. On synthetic sequence it read `FRAMESHIFT` at
12% with 10% divergence and 42% with 30%, and 168 of those 203 calls had no run. All 13 real `FRAMESHIFT`
calls have an A run of 13 to 29 bases. Requiring the run costs a real slip outside a repeat, which reads
`OTHER_FRAME` at medium certainty and still names the part.

**A wider `SPLICE_SLACK` instead of the run.** It would catch more introns by raising the chance rate of a
pair, which is already 9 to 24% at one change.

**Requiring the model to end at the change.** On real strains the slip mostly lies under a model that
splices around it or starts after it, so that rule read run differences of one base as `OTHER_FRAME`.

**Concluding a cause from served calls.** Answers such as an in-frame indel "cannot be the change", or "the
assembly likely miscounts the run", read a cause out of records that do not hold it.
`indel_frame_effect` is one value per site, and nothing links a sample's row to it: on
`Variant_Pf3D7_01_v3_283234`, `RV_3630` has genotype 1 and allele `A`, which is not the base that site's
deletion leaves. An SNV row shows coverage at that base and nothing about indels. A host reads the
records.

**Treating a rejected frame change as a truncation.** Each guard added to reject a frame change fell
through to `GENOME_ENCODES`, which says the part lies in the model's reading frame. Review rounds kept
finding new failures from that one root, so a part that is not in the open frame now has its own answer.

**A splice pair anywhere in the stretch.** It lost real one-base changes at 16 to 71% once the reference
diverged 20% or more.

**A frame label on `GENOME_ENCODES`.** A host that reads only the verdict would go on reporting an
annotation truncation.

**The longest repeat of any kind.** The example has 29 A beside eleven copies of `AAAAC`, and the count
that differs between the strains is in the homopolymer.

**A table of samples per genome.** It would hold one species of one site and go stale.
