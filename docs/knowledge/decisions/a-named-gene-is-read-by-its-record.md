---
type: Decision
title: A named gene is read by its record
description: Every gene a served check or lookup names is read by its own gene record (and its protein by one transcript record), an id no record names goes to the text search, an ortholog group is the one Orthologs table read, a host's one id-list read is the only upload, and an unread intron is explained in stages; and why a dataset per 150 ids, GenesByOrthologs and a protein attribute on the gene record were rejected.
tags: [audit, wdk, jbrowse, datasets]
status: stable
---

# The choice

WDK reports over an arbitrary gene list only through `GeneByLocusTag`'s `ds_gene_ids`
parameter, which takes an id-list dataset, and WDK has no call that deletes a dataset.
Every dataset a check uploads stays in the researcher's account. So no tool a chat
calls uploads one, except a tool whose WDK search takes only an id list, which says so:

- **A named gene** is one gene record read by its primary key
  (`record_rows`, `veupathdb_mcp/audit/record_reads.py`), with the attributes
  `RECORD_ATTRIBUTES` and the `GeneTranscripts` table, whose longest protein length is
  the row's. The gene record type declares `orthomcl_name`, `name`, `product`,
  `start_min` and `end_max` where a transcript report serves `gene_orthomcl_name`,
  `gene_name`, `gene_product`, `gene_start_min` and `gene_end_max`
  (`tests/unit/fixtures/gene_record_attributes.json`). A call names at most
  `RECORD_READS_PER_CALL` (80) genes; more is refused before any read.
- **An id** is read the same way. On QA plasmodb on 2026-10-22 the gene record read
  resolves a previous id (`PF10_0316`) and an alternate id (`CZT98581.1`) to
  `PF3D7_1032400` and answers 404 for its transcript id `PF3D7_1032400.1`
  (`tests/unit/audit/fixtures/records_pfal3D7_piga.json`). A 404 sends the id to
  `GenesByText`, which takes the one gene whose own id, or whose transcript id, is the
  id, and reads that gene's record. WDK answers 300 when an id maps to several records;
  that id is refused naming the site's answer. The `GenesByText` answer to a
  transcript id is not recorded; its test serves a synthetic answer.
- **A protein** is one gene record read of the `GeneTranscripts` table and one
  `transcript` record read (primary key `gene_source_id`, `source_id`, `project_id`) of
  the longest coding transcript, the lowest transcript id on a tie
  (`record_proteins`). The gene record type declares no `protein_sequence`.
- **An ortholog group** is the gene record's `Orthologs` table, one read whatever its
  size (`orthologs_of`): each other member with its organism, protein length, product,
  synteny and reference-strain flag. The recorded group of PcyM_0736700 lists 522
  members, and its lengths class the gene as the 529 gene rows did
  (`tests/unit/audit/test_ortholog_groups.py`). A member the table gives no length
  counts as not coding. That the table gives a pseudogene member no length is assumed:
  the recorded groups hold no pseudogene member. Location fields are read only for the
  genes a check places: the gene and a split partner. The strain check places the
  strain's other group members with one range read of the organism's
  `annotated_transcripts` GFF over the window (at most `ANNOTATION_MAX_GROUPS` (4)
  chunk groups), not with their records; on QA plasmodb its gene features carry the
  gene id as `ID` (`tests/unit/audit/fixtures/strain_pcynM_pkac.json`).
- **A lookup** reads ids the same way (`read_gene_ids`,
  `veupathdb_mcp/gene_lookup/records.py`): `resolve_gene_ids_to_records`, at most
  `RECORD_READS_PER_CALL` ids, and the fill of a `lookup_gene_records` hit that lacks an
  organism or a product. A result's `previous_ids` stays empty, because only the
  transcript report serves `gene_previous_ids`. `resolve_gene_ids`, the id-list read, stays
  for a host that names more ids than one call reads.
- **A tool whose WDK search takes only an id list** (`enrich_gene_ids`,
  `run_control_tests_on_search`, `run_control_tests_on_step`, `create_gene_set_step`)
  writes one dataset per call, and its description says so. A test runs every served
  tool with the upload refused and holds the tools that reach it equal to the tools whose
  description says so.
- **A host's gene rows** become group members through `GroupMember.of_row`, which keeps
  the coding rule: a pseudogene row, or a row of no protein gene type, has no length.
- **A host's run** reads its gene list once, with `one_list_rows`: one id-list dataset
  of at most `MAX_LIST_IDS` (400) ids, its report paged by `LIST_PAGE_RECORDS`, at most
  `LIST_MAX_PAGES` (4) pages; a report of more transcripts is refused.
  `locus_tag_answers` stays behind it and behind the whole-genome checks.

The intron check stages its evidence. Junctions judge first, from at most
`JUNCTION_TRACKS_READ` (4) junction tracks of the organism; an intron they leave
`UNEXPLAINED` reads the peptides split across it, and a peptide clears only such an
intron (the organism's
`unifiedGenomicMassSpec` track, at most `PEPTIDE_MAX_GROUPS` chunk groups counted by
`TabixReader.chunk_group_count` before any group is read), then its splice motif from one
genome window, then its depth over one coverage track. A motif holding a base other than
A, C, G or T is an assembly gap, not a splice site: on QA vectorbase 330 of the 331 bases
of AGAP007279's annotated intron 44981063-44981393 are N, so that intron reads no motif
and no depth and stays `UNEXPLAINED`. `RETAINED` reads the intron's median depth against
the exons' median and needs 0.9 of the intron's bases covered, because a minimum is
undone by one base without a read. The experiment is chosen by measurement: the first
time a gene of an organism reaches the coverage stage, the total summary of every
stranded coverage file is read from its bigWig header (`BigWigReader.summary`), at most
`COVERAGE_HEADERS_READ` (200) per organism and process, and the
`COVERAGE_CANDIDATE_PAIRS` (3) stranded pairs covering the most bases are shortlisted.
Each gene then reads its depth on the 6 shortlisted subtracks and takes the one with the
highest exon median, which also settles its strand, because a subtrack's name does not
say the gene's strand. agamPEST lists 168 such files in 84 pairs; on QA on 2026-10-22 the
shortlist is salivary glands paired-end, E-MTAB-2880:E_20h_F and midguts paired-end, and
AGAP003685's intron is `RETAINED` on `E-MTAB-2880:E_20h_F (unique reverse)` (intron
median 4.17, exon median 7.83, 0.988 covered) (`tests/unit/audit/test_introns_recorded.py`).
Header reads are a per-organism cost, `COVERAGE_HEADERS_READ`; the per-gene cost
`INTRON_STORE_READS` is 1 window + `PEPTIDE_MAX_GROUPS` + 6 depth reads of
`BIGWIG_READS_PER_DEPTH` each. A sequence a bigWig
does not list is depth not read, never zero depth. A track list, header, window, peptide
or depth read the site refuses leaves that stage unread and names the reason in
`evidenceUnread`; a refused header drops only its pair. The organism's track list and
coverage choice are read once per organism and JBrowse client, concurrent checks
sharing one read, and are kept for the process, not for one run. A refused RNA-seq
track list is not kept: the organism's next gene reads it again. After
`TRACK_LIST_TRIES` (2) failures the list is not read for `TRACK_LIST_RETRY_SECONDS`
(600, on a monotonic clock), the coverage stays unread with a reason that says when
the list is read again, and the count starts over after that. A strain call makes at most `STRAIN_STORE_READS` (5) store reads
beyond those made once per organism: one genome window and up to
`ANNOTATION_MAX_GROUPS` annotation range reads, one per chunk group.

# What was rejected

**A dataset per 150 ids.** It is what `locus_tag_answers` did; every row and protein
read left datasets in the account that nothing can delete.

**A lookup through `GeneByLocusTag`.** It read up to 200 ids in two requests, and each
call left a dataset in the account, under a tool annotated read-only.

**`GenesByOrthologs`.** Its `gene_result` parameter is an input step, so a group read
would write a step into the account; the `Orthologs` table already lists the group.

**`protein_sequence` on the gene record.** The gene record type does not declare it, so
the read is refused; the transcript record does.

**The site's track order, the label order, or the mean depth.** The site's order changes
between two reads of the same list; the first pair by label is an experiment chosen by
its name; and a mean over covered bases ranks sparse, deep small-RNA libraries first. On
agamPEST each of the last two picked a small-RNA study with no reads over AGAP003685.

**The smallest depth over the intron.** One base without a read refuses an intron the
rest of the reads cover.

**A strand subtrack chosen by its name.** The name follows the file (`firststrand`,
`secondstrand`), whose relation to the gene's strand depends on how the library was
made; the deeper subtrack over the exons is a measurement.

Falsified by `tests/unit/audit/test_record_reads.py`,
`tests/unit/audit/test_ortholog_groups.py`, `tests/unit/audit/test_group_member_rows.py`,
`tests/unit/audit/test_no_chat_dataset.py`, `tests/unit/audit/test_strain_sides.py`, `tests/unit/audit/test_intron_stages.py`,
`tests/unit/audit/test_intron_evidence.py`,
`tests/unit/audit/test_introns_recorded.py`,
`tests/unit/gene_lookup/test_a_lookup_reads_by_record.py` and
`tests/unit/test_every_dataset_write_is_described.py`.
