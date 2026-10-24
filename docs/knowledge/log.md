# Knowledge log

## 2026-10-24 - 0.2.0b47

- A tightened limit, not breaking for hosts: no published name is removed or renamed.
  `build_phyletic_expression` and `write_phyletic_expression` admit an expression only
  inside three caps, each checked as the build grows and on the rendered expression,
  before its count; a pattern with no compare is refused before any read. OrthoMCL's
  expression parser recurses once per AND or OR operator and reads the rest of the
  expression again at each level, so its stack depth grows with the operators and its
  work with operators times characters. Each cap is the measured safe range:
  - `MAX_EXPRESSION_TERMS = 2000` OR terms: the longest ladder the QA recording
    answered (2,000 terms, 53,779 characters, 14.2 s). The recorder sent no longer
    ladder, so no more operators were measured safe. Inside the old 645,028-character
    cap a ladder runs to about 22,000 terms.
  - `CHARACTERS_WITHIN_READ_TIMEOUT = 150_000` characters: veupathdb-py reads a
    component site with a 30 s timeout (`READ_TIMEOUT_SECONDS`, the client's
    `component_timeout`) and a search is not retried, so a count past 30 s fails
    whatever the 300 s call budget says. The character fit predicts 24.6 s at 150,000;
    the longest recorded row under 30 s is 165,028 characters at 21.7 s.
  - `MAX_EXPRESSION_WORK = 160_000_000`, OR terms times characters: half the largest
    product measured safe on QA OrthoMCL outside the recording, 250 terms of three codes
    at 1,298,778 characters (324,694,500, 17.2 s; 645,028 characters took 8.9 s). Within
    the term and character caps it binds a long expression: 2,000 terms admit at most
    80,000 characters.
- A refusal raises `PhyleticExpressionTooLargeError`, a `ValidationError` with `limit`
  (`terms`, `characters` or `work`), `terms`, `characters`, `cap` and `work`. Its detail
  says the pattern expands past what one search can run, gives the OR terms and
  characters, names the cap, and says it is a limit of this library, not a failure of
  the site. The error and the three caps are exported from `veupathdb_mcp.catalog`.
- A stated `phyletic_expression` is held to the same caps where
  `validate_search_params` checks its grammar, before the taxonomy read, and the
  `phyletic_expression` help states the three caps.
- The count-time model stays the character fit, 3.94 s plus 0.138 ms per character
  over the eight recorded rows. The recording varies terms (ladders, two codes a term)
  and codes (250 terms of 9 to 513 codes) apart, so a fit by terms and codes exists:
  3.36 s plus 3.51 ms per term plus 0.668 ms per code, worst row 18.6% off against
  22.8%. It is not taken: on 250 terms of three codes, measured outside the recording,
  it predicts 4.7 s at 645,028 characters where the count took 8.9 s, and the
  character fit predicts more than the count took. The caps are the hard guard.
- The pattern-level bound of 128 terms, nested ones counted, is `MAX_PATTERN_TERMS`
  (was `MAX_TERMS` in the unpublished `catalog.phyletic_pattern`), apart from the
  written expression's `MAX_EXPRESSION_TERMS`.
- The read ceiling is unchanged, 690 reads: `SiteCost.reads_within` still reserves the
  count of the longest recorded expression.
- `scripts/record_phyletic_site_limits.py` plans nothing past `MAX_EXPRESSION_TERMS` or
  `MAX_EXPRESSION_WORK`: its ladders stop at 2,000 terms and its widest unit is 128
  codes. A new recording therefore holds no 645,028-character row.
- Every build the unit suite made under 0.2.0b46 inside the three caps, 205 of 209
  (the seven recorded count wires among them), is made again with the same expression.
  The four outside them were tests of long expressions, now refused or rebuilt
  smaller.
- What a host does to take this release: nothing, unless it shows its own words for a
  phyletic refusal; it may catch `PhyleticExpressionTooLargeError` to say the pattern
  is too large for one search.

## 2026-10-24 - 0.2.0b46

- Breaking for hosts. An audit run uploads no dataset. `read_gene_list(site_id,
  gene_ids)` reads a run's gene list by record, one gene record read per id
  (`found_row`), at most `MAX_LIST_IDS` (400) ids, and answers one `GeneRow` per gene;
  an id no record names is dropped, as the list report dropped it. `upload_gene_list`,
  `GeneListDataset`, `LIST_PAGE_RECORDS` and `LIST_MAX_PAGES` are gone. Each run had
  left one id-list dataset in the researcher's account per site, a single-gene run too,
  and WDK's `DatasetService` serves POST and GET only, so nothing removed it. An inline
  id list is not a way around the upload: `DatasetParam.validateValue` refuses a
  `ds_gene_ids` value that is not the id of a dataset the requesting user owns. A
  test reads a list over the HTTP wire and asserts the exact requests: the session
  warm-up, `GET /users/current` and one `POST /record-types/gene/records`, and no
  `/datasets`. On the three genes recorded both ways (PF3D7_1032400, PF3D7_1133400,
  PF3D7_1222600) the record row equals the `GeneByLocusTag` row field for field, and
  the thirteen recorded check results are byte-identical before and after.
- What a host does to take this release: call `read_gene_list(site_id, genes)` where it
  called `read_gene_list(await upload_gene_list(site_id, genes))`, and drop the
  `GeneListDataset` it stored for a retry, together with the stored field that holds
  it.
- A host that prices a run's reads counts one record read per listed gene, not a fixed
  list read, and announces no dataset left in the account. A read that fails partway
  starts again from the first gene, since nothing is stored between attempts.

## 2026-10-24 - 0.2.0b45

- Additive, not breaking. Two caps a host had to copy as numbers or read out of a
  sentence are typed and exported from `veupathdb_mcp.audit`:
  - `PREMATURE_STOPS_LISTED = 20` is the most stops `PseudogeneCheck.premature_stops`
    lists, and `PseudogeneCheck` carries `premature_stops_truncated: bool`
    (`prematureStopsTruncated` on the wire, default false): true when the frame holds
    more stops than the list. The cap applies where the check is built, never in the
    model, so a record stored under one cap still validates under another; the model
    refuses only a cut list that is empty. A synthetic frame with 23 stops lists the
    first 20 and reads `premature_stops_truncated` true; one with exactly 20 reads it
    false.
  - `JUNCTION_TRACKS_READ = 4` moves from `introns_inputs` to `introns` and is
    exported. `IntronAudit` carries `junction_tracks: JunctionTracks | None`
    (`junctionTracks`, null when the call ends before the track list is read), where
    `JunctionTracks` holds `organism_abbrev: str`, `listed: int` and `read: int`.
    The read count is the lesser of `listed` and the cap where the record is built;
    the model refuses only a `read` past `listed`, so a record stored under one cap
    still validates under another. The sentence
    "{abbrev} lists {listed} junction tracks; the first {read} were read" in
    `evidence_unread` is written from the record alone (`JunctionTracks.cap_note`,
    when `read` is under `listed`), and the audit refuses a cut its
    `evidence_unread` does not name. A NOT_CHECKED answer whose tracks all refuse
    the gene's sequence now names the cut too. On the recorded QA plasmodb case
    PcyM_0736700 the record reads `pcynM`, listed 1, read 1.

## 2026-10-24 - 0.2.0b44

- Additive, not breaking. `UnreadIntron` carries `spans_assembly_gap: bool`
  (`spansAssemblyGap` on the wire, default false): true when the intron's motif from the
  genome window holds a base other than A, C, G or T. The gap is a fact about the
  genome, not an outcome: such an intron carries no motif and no depth, and the model
  refuses one that carries either, but its junctions still decide its outcome. Gap
  evidence plus a junction within 30 bases at both ends judges `SHIFTED` with
  `spans_assembly_gap` true; the staged read reads motifs only for `UNEXPLAINED`
  introns, so a gap there stays `UNEXPLAINED`. The sentence
  "the intron {start}-{end} spans an assembly gap" in `evidence_unread` is now written
  from the field (`UnreadIntron.assembly_gap_note`), so a host reads the field and never
  matches the sentence. On the recorded QA vectorbase case AGAP007279 the intron
  44981063-44981393 reads `spans_assembly_gap` true; the recorded RETAINED intron of
  AGAP003685 reads it false.
- `IntronEvidence` carries the intron keys over a gap (`gaps`), and `needs_motifs` and
  `needs_depth` skip an intron over a gap, so the staged read no longer keeps its own
  list of gap spans.

## 2026-10-24 - 0.2.0b43

- Breaking for hosts. Three arguments are gone and one sidecar changes shape, and a
  step's record class is read from the catalog or from WDK where each one stated it:
  - `create_gene_set_step(site_id, gene_ids, strategy_name)`, the served tool, takes no
    `record_type`. A host drops the argument from its calls.
  - `frozen_step_id(site_id, gene_ids, *, strategy_name)` takes no `record_type`. A
    host drops the third positional argument.
  - `EnrichmentService.run_batch(..., search_name=..., parameters=...)` takes no
    `record_type`. A host drops the keyword; the class of `search_name` is read.
  - `build_snapshot_from_wdk` returns its wire sidecar as `dict[str, WireStep]`
    (`veupathdb_mcp.wdk.WireStep`: `record_class: str | None`, `parameters`), where
    it was `dict[str, dict[str, str]]`, and `canonicalize_synced_parameters` takes that
    shape. A host reads a step's wire values as `wire[step_id].parameters`, and a host
    that builds a sidecar of its own builds `WireStep(record_class=..., parameters=...)`
    with the class WDK states for the step, or `None` where WDK states none.
  - `count_plan_steps` and `compute_plan_step_counts` keep their arguments, and the
    plan's `record_type` (a field of the client's `StrategyAst`) no longer decides
    the class of any step. A host that states another class for a step's search gets
    the step counted under its listed class.
- Every step of a counted plan is read under the record class the catalog lists its
  own search under (`assign_step_record_classes`, through
  `make_record_type_resolver`), and a combine under the class of the steps it
  consumes (`record_class_of`), on both count paths. Every step was read under the
  plan's `record_type`, so on QA OrthoMCL a `GroupsByNameList` leaf under a
  `sequence` root was read as
  `GET /record-types/sequence/searches/GroupsByNameList?expandParams=true`, and the
  site answered 404, once per variant of a `compare_search_variants` call. A lone
  group leaf stated as `sequence` was sent to
  `POST /record-types/sequence/searches/GroupsByNameList/reports/standard`, which the
  site test (`test_a_plan_step_is_created_under_its_own_record_class.py`) answers 404,
  so the step counted as null. A step whose search the catalog lists under no record
  type is refused by name (`UnlistedSearchError`) before any request, and never falls
  back to the plan's class.
- A saved strategy's steps are decoded under the record class WDK states for each
  step (`WDKStep.record_class_name`, carried on `WireStep`), not under the strategy's
  class. A `GenesBySnps` (transcript) root over a `SnpsByLocation` (snp) leaf read
  `[('transcript', 'SnpsByLocation'), ('transcript', 'GenesBySnps')]`; the leaf read
  is a 404, so its parameters stayed undecoded. It now reads
  `[('snp', 'SnpsByLocation'), ('transcript', 'GenesBySnps')]`
  (`test_strategy_snapshot.py`).
- A step names no class when its search is gone: WDK writes `recordClassName` as
  `step.getRecordClass().map(RecordClass::getUrlSegment).orElse(null)`
  (`WDK: Service/src/main/java/org/gusdb/wdk/service/formatter/StepFormatter.java`,
  line 88). Such a step reads no spec and keeps its wire values in the sidecar, and is
  logged by step id and search name ("A WDK step names no record class"); the rest of
  the strategy decodes.
- `resolve_wdk_context` is removed, with the helpers only it used
  (`_extract_step_search_context`, `_decode_step_parameters`, `_count_strategy_steps`,
  `resolve_root_step_id`). Nothing called it, here or in PathFinder, and it took a step
  id without checking that the step belongs to the strategy it named. Breaking for any
  host that imports it from `veupathdb_mcp.wdk` (PathFinder does not). `GeneSetWdkContext`
  stays: PathFinder reads it.
- An unreachable second copy of the database-URL check after the `return` of
  `EmbeddingSettings._database_url_from_the_postgres_settings` is removed.
- The gene-list step and the enrichment target read their class the same way:
  `GeneByLocusTag` is created under the class the catalog lists it under, and a site
  that lists none refuses before the dataset upload; `run_batch` reads the class of the
  search it is given, where it fell back to `transcript`.
- A bearer the transport gate cannot verify because the VEuPathDB identity provider
  cannot be read is refused with a 503 `application/problem+json` body, titled
  "Identity provider unavailable", with `Retry-After: 30`, by the gate's own
  `on_error`. The verifier raises `IdentityProviderUnavailableError`, an
  `AuthenticationError`, from the client's `ExternalServiceError`. The error escaped
  the gate before: with `https://auth.veupathdb.org/jwks` unreachable, a call carrying
  a user bearer was logged as "Exception in ASGI application" and answered a raw 500.
  The body names no URL and no client error text.
- A bearer that is not a JWT (its header does not parse, `jwt.get_unverified_header`)
  names nobody before the signing key is read, so it is refused with the 401 challenge
  whether or not the identity provider answers. `pyjwt` is now a declared dependency.
- Unchanged, and checked: a control run on a search reads both classes from the
  catalog (`listed_record_type`); a control run on a built step takes the class WDK
  reports for it and copies its tree server side (`duplicated-step-tree`); a
  separation measures only searches the catalog lists under `transcript`
  (`search_skip`), so its leaves and combines are created under that class.

## 2026-10-24 - 0.2.0b42

- An AND product charges each pair it tries by its atoms, the left clause's plus the
  right clause's, where it charged one flat cost a pair; the index sums them from per
  bucket atom totals without building a pair. A pair's merge takes time in proportion
  to its atoms, and a pattern of 128 terms makes clauses of hundreds of atoms, so a
  flat charge let the build run many times its prediction. On the recorded OrthoMCL
  taxonomy, an `all_of` of two `any_of`s of 60 `each_genome_of` counts over all 857
  genomes is charged 106,500 pairs, about 0.15 s at the old 1.44 us a pair, and the
  call ran 41.2 s. `MEASURED_SECONDS_PER_PAIR`, `SECONDS_PER_PAIR` and `Guard.pairs`
  are gone; `Guard.atoms` counts the charge.
- The work around a product is charged too. Each clause an AND product or an OR merge
  admits charges its atoms (`Guard.admit(..., atoms=)`), and the rendering charges every
  unit it writes, so the clause admissions, the widths and the string build come out of
  the budget with the pairs.
- The first cover read of each distinct genome set is charged before it is read
  (`Guard.covers`), and a pattern past the budget is refused by name with its sets.
  `pattern.probes` takes the `Guard` and reads each compare side's cover through it,
  and `write_phyletic_expression` runs it in a worker thread (`probed`) before the
  first read. `written` builds on `Guard.after(reads)`, which keeps the probe step's
  covers, their charge and its start, so a side's cover is read and charged once a
  call. A pattern whose sides pass the budget is refused before any read.
- `MEASURED_SECONDS_PER_ATOM` is 2.83 us and `MEASURED_SECONDS_PER_COVER` 19.14 ms, each
  the most over its measured shapes on that taxonomy, the median of 7 runs with the
  garbage collector on, each genome's cover read first for the atoms; `HOST_MARGIN`
  stays 2. Per atom (`atom_cost_median`, 25 shapes): pairs that contradict 0.11 to
  0.30 us, wide pairs that merge 0.63 to 0.83 us at widths 8, 32 and 128, narrow pairs
  that merge 1.37 us, duplicate-heavy products 0.68 to 1.06 us, patterns with their
  rendering 0.10 to 0.96 us, and two same-side totals compares at a largest count of
  16,000 with their rendering 2.83 us. Per cover: every genome 0.40 ms (20 sets), a
  clade or all but one clade 1.77 ms (46, 47), a species 15.32 ms (640), a genome
  15.64 ms (857), all but one genome 19.14 ms (200).
- Actual time over the charge at the measured rate, before the margin
  (`charge_bound`): duplicate-heavy 0.36, duplicate-heavy wide 0.27, totals AND
  totals at 16,000 1.00, per_genome right 4 at 340 0.59, per_genome AND per_genome at
  300 0.31, each_species_of ALL 0.75, none_of any_of 40 0.60; after the margin of 2,
  every shape is at or under 0.50.
- The call has a wall-clock deadline, fixed at its start before the taxonomy read
  (`clock`, `Guard(start=)`): that time plus the 300 s budget less the count's fixed
  cost. The probe covers and the site reads run on the same clock, so slow reads
  shorten the build. Every charge and admission reads the clock, an admission takes
  the count of its own characters off the deadline, and a step past it is refused by
  name with the seconds the call ran. It ends a build the estimates miss in the worker
  thread, which cannot be cancelled.
- Unchanged: the two same-side totals compares build 152,697 characters in 0.4 s at a
  largest count of 4,000 and 638,701 in 1.9 s at 16,000 (charged 480,024 atoms and 3
  covers with its rendering, about 2.8 s), and are refused at the cap at 30,000; `each_genome_of` at most 1 protein
  admits 10 genomes (111,612 characters) and 12 (536,572) and refuses 13 at the cap;
  the fuzzed truth check (8 seeds, 100 patterns each, budget shrunk to 7 s) has no
  mismatch, and refuses 5 patterns more than 0.2.0b41 by the cover charge.

## 2026-10-24 - 0.2.0b41

- `build_phyletic_expression` bounds its site reads before the first one. A distinct
  compare side takes at most 25 count reads (`READS_PER_PROBE`, derived from
  `FIRST_PROBE` and `LAST_PROBE`), and a call admits at most the reads the 300 s budget
  leaves after the count of the longest admitted expression (about 92.8 s), at the
  measured 0.3 s a read (`SiteCost.reads_within`: 690 on the current fit). A pattern
  whose distinct sides would need more, 28 sides or more, is refused by name before any
  read, and
  `GroupCountReports` refuses the read past the ceiling even when the prediction is
  wrong. The expression's own count is one read on its own.
- A pattern nests at most 8 levels (`MAX_DEPTH`) and holds at most 128 terms, nested
  terms counted (`MAX_TERMS`); a combination past either is refused at validation, and
  the tool description states both.
- An OR merge is admitted after each clause it adds, like an AND product, and the
  parts of every merge and product are built one at a time, so a refused build holds at
  most the cap and one clause. An OR merge that meets an always-true part before it
  passes the cap is still always true.
- An AND product no longer tries every pair of clauses. It indexes the added side by the
  set its clauses most often hold to one exact count, and pairs a clause only with the
  clauses whose count on that set its own bound admits, so two compares over one side
  try pairs linear in the side's largest count: at 16,000, 96,006 pairs where every pair
  was 2.56e8, and the build of the 638,701-character expression takes 1.7 s where it
  took 196 s. Every pair a product tries is charged to the guard before it builds, at
  0.72 us a pair (`SECONDS_PER_PAIR`, measured on 9e6 contradictory pairs on a
  developer machine), and that time comes out of the 300 s budget with the reads and the
  count. A build predicted past it is refused by name, with its pairs, before its
  clauses are built.
- The read ceiling is never negative, and the pair cost carries a host margin of 2 over the cost measured on one machine (`MEASURED_SECONDS_PER_PAIR`, `HOST_MARGIN`).

## 2026-10-23 - 0.2.0b40

- A phyletic search resolved with neither species list raises `PhyleticListError`, never
  binding the site's hidden `profile_pattern` default (`hsap=1T` on QA plasmodb
  `GenesByOrthologPattern`, which would filter to genes with a human ortholog); the website's
  form always derives the pattern from the two lists. An unknown parameter name lists only
  visible names. `AllOf`, `AnyOf` and `NoneOf` are rebuilt, so a combined pattern serializes.
  The served builder says a host should keep a long expression and bind it by reference.
### One phyletic expression builder

- Breaking for hosts. `build_protein_count_comparison`, `build_clade_only_expression`
  and `build_every_species_expression` are no longer served, and
  `compare_protein_counts`, `clade_only_expression`, `every_species_expression`,
  `ProteinCountComparison`, `ProteinCountLadder`, `CladeOnlyExpression`,
  `EverySpeciesExpression`, `SpeciesUnit`, `MAX_COUNT_REPORTS`,
  `CLADE_ONLY_COUNT_REPORTS` and `EVERY_SPECIES_COUNT_REPORTS` leave
  `veupathdb_mcp.catalog`. A builder per question shape pulls a near shape toward its
  own reading.
- `build_phyletic_expression(site_id, pattern)` replaces them, served read-only with a
  300 s call budget, and `write_phyletic_expression(site_id, pattern)` is the same call
  in process. `pattern` is the tagged union `PhyleticPattern` on `kind`: `count`
  (`CountTerm`: a set, a measure of `genomes`, `proteins` or `share`, a condition of
  `at_least`, `at_most`, `exactly`, `more_than`, `fewer_than` or `absent`, a value;
  measure and value default to none and are required unless the condition is
  `absent`), `compare` (`CompareTerm`: two sets, a reading of `per_genome`, `totals`
  or `averages`, a condition, a factor), and `all_of`, `any_of`, `none_of` (`AllOf`,
  `AnyOf`, `NoneOf`) over patterns. A set is `codes` (`CodeSet`, where `ALL` is every
  genome), `all_except` (`AllExcept`), `each_species_of` (`EachSpeciesOf`) or
  `each_genome_of` (`EachGenomeOf`); a comparison takes the first two. A genome with
  no protein counts 0. A share is a genome count per set, ceiling for at_least, and
  exactly holds only on a whole count. A per-genome compare against one right genome
  writes one exact band per count. The result, `PhyleticExpressionResult`, gives
  `expression`, `reading` (the client's `describe`), `groups`, `codes` and
  `maximumReads`.
- Requests per call: one count report for the expression, after `check_expression`
  passes. A comparison adds the bisection reads of its right side's largest count
  (`B>=128`, doubling, then halving), each distinct side read once per call, one report
  at a time. A probe that still answers groups at 65,536 or more is refused.
- Admission stops at the longest expression the site was measured to answer, read from
  the QA recording `catalog/data/orthomcl_phyletic_site_limits.json` (runtime package
  data the wheel ships): 645,028 characters. A longer expression is refused by name, as
  longer than that; it needs recorded rows before it is admitted. A count's time follows
  characters: `catalog/site_cost.py` fits the recording as about 3.9 s plus 0.138 s per
  1,000 characters (every row within 25%, the worst at 22.8%), plus 0.3 s per bisection
  probe, and a pattern predicted past the 300 s budget is refused as a second guard.
  Each refusal names the OR terms and characters, before the count, and before any read
  for a pattern with no compare. The build is admitted step by step on its merged
  clauses, after contradictions drop, and its rendering on its exact characters; no
  term count is fixed. The expansion, parse, check and reading run in a worker thread.
  A site refusal reaches the caller as the site wrote it.
- The result carries the whole expression, the value for `phyletic_expression`. Its
  `reading` is the client's reading up to 2,000 characters (`READING_LIMIT`), and past
  that an outline of the pattern with its OR terms and characters, at most 2,000
  characters.
- `scripts/record_phyletic_site_limits.py` (at most 30 count reports, one at a time,
  stopping at the first refusal or at 300 s) ran on QA OrthoMCL: ladders of 250 to 2,000
  terms (6,278 to 53,779 characters) took 4.5 to 14.2 s, and 250 terms over units of 8
  to 512 codes (15,028 to 645,028 characters) took 6.5 to 103.2 s, all answered. The
  ladder above 2,000 terms was not sent.
- It pins veupathdb-py 0.1.0b23, which parses an expression in linear time, reads the
  tree once per expression, and publishes `PHYLETIC_ROOT_CODE`.
- The `phyletic_expression` help keeps its grammar, precedence, absence and length
  rules, drops every recipe, and names `build_phyletic_expression`, as does
  `EXPRESSION_LOOKUP_HINT`. `tests/unit/catalog/test_the_help_recipes_parse.py` and
  `scripts/record_orthomcl_every_species.py` are deleted. The five recordings under
  `ORTHOMCL_COUNTS` stay, and `tests/unit/catalog/test_the_count_recordings_replay.py`
  replays each against the pattern it records on the recorded taxonomy: the three
  two-genome ladders as `compare` totals more_than (3,896, 13,354 and 11,130 groups),
  the three clade-only counts as `count` at_least 1 genome with `all_except` absent
  (558, 54,039 and 1,511), and the every-species count as `each_species_of` share
  at_least 50 (2,505).
- What a host does to take this release: call `build_phyletic_expression` where it
  called one of the three builders, read the input and result names above from
  `veupathdb_mcp.catalog`, and replace its conformance samples for the three removed
  tools with one sample of the new tool. The served tool count is forty-two.

### No hidden parameter reaches the model

- `build_sheet` (`catalog/param_sheet.py`) lists visible parameters only, and
  `SheetEntry.hidden` is gone. Commit 2e4ce60 (0.2.0a32) listed a hidden parameter that
  has a vocabulary, marked hidden, on the reading that hidden means not shown, not fixed.
  The website does not read it that way: wdk-client's `DefaultQuestionForm.tsx` draws
  only groups whose `displayType` is not `hidden`, and `extractParamValues`
  (`Utils/WdkUser.ts`) gives every parameter, hidden ones included, its value from the
  URL's initial params, the saved step, or `initialDisplayValue`. A person never sets a
  hidden value, and a host hands the sheet to a model, so the model set them. Measured on
  QA plasmodb `GenesByRNASeqpfal3D7_Bartfai_time_series_rnaSeq_RSRCPercentile`: the
  hidden `channel` (group `_hidden`, `isVisible: false`, `initialDisplayValue`
  `Channel 1`, vocabulary `Channel 1`, `Channel 2`) was on the sheet, and a count with
  `channel="Channel 2"` and a valid profileset answered 500 Internal Error (WDK
  `WdkEmptyEnumListException` on `samples_percentile_generic`).
- The other paths that showed a hidden parameter are closed. `get_parameter_options`
  (`read_parameter_options`) refuses one by name with `HiddenParameterError` ("the site
  sets it"), and a visible parameter's `controlsVocabOf` names visible parameters only,
  as the overview's does. The served `get_search_param_specs` lists visible parameters
  and visible dependents; `build_param_specs` stays whole for a host's form. The
  resolve walk binds a hidden parameter at its default, never opens a slot for one or
  names one in `unresolvedRequired`, and refuses an override that names one. A hidden
  required parameter with no default refuses the search (`HiddenParameterError`, "no
  value the site sets"); a hidden input step is left to the step tree.
- Breaking for hosts. `resolve_params_with_intent` takes `definition`, the search's
  published parameters, and derives `profile_pattern` from `included_species` and
  `excluded_species` with `derive_phyletic_overrides`. A stated `profile_pattern` is
  refused as a hidden parameter, and a stated map as no parameter of the sheet. Lists
  that name no entry, or select nothing, or come without `definition`, are refused with
  `PhyleticListError`. The served `resolve_search_parameters` passes the definition.
- The values `validate_parameters` returns carry a hidden parameter at its
  `initialDisplayValue` when the caller states none and the parameter forbids an empty
  value (the client's `fill_hidden_required_defaults`); a hidden parameter that allows
  empty is not filled there, where the website sends every hidden one. A hidden value a
  caller states still travels as stated: some searches take one from a form of their
  own (`profile_pattern` on `GenesByOrthologPattern`, the `eda_*` parameters of the
  EDA-backed searches), and a value WDK derives from a visible one
  (`eda_sample_table_suffix` from the organism) differs from the static default.
- Falsified by `tests/unit/catalog/test_a_hidden_parameter_is_off_the_sheet.py` (the
  rewrite of `test_a_hidden_choice_is_on_the_sheet.py`),
  `tests/unit/catalog/test_a_hidden_parameter_never_reaches_the_model.py` and
  `tests/unit/catalog/test_a_hidden_parameter_takes_the_sites_value.py`, on the recorded
  `GenesByNgsSnps` and its `_hidden` group.
- What a host does to take this release: stop reading `SheetEntry.hidden`, stop offering
  a hidden parameter's vocabulary as a choice, catch `HiddenParameterError` from
  `read_parameter_options` and `resolve_params_with_intent`, and pass the two species
  lists with `definition` to `resolve_params_with_intent` in place of a derived
  `profile_pattern`, catching `PhyleticListError`.

## 2026-10-23 - 0.2.0b39

- `read_each_gene_id(site_id, gene_ids)` (`veupathdb_mcp.gene_lookup`) answers each id on
  its own, in the order given: a `GeneIdFound` with the records the id names, or a
  `GeneIdRefusal` (`veupathdb_mcp.audit`) whose `problem` is `notFound`,
  `severalGenes`, `notAnId` or `tooManyMatches`. One id that names several genes refuses
  that id alone. `read_gene_ids`, `rows_named` and the served
  `resolve_gene_ids_to_records` read the same per-id answers through `each_named`, keep
  their whole-list answer, and stop at the first refused id. The fill of a
  `lookup_gene_records` hit reads each id on its own, so one ambiguous id leaves the
  other hits filled. `genes_by_text` and `several` answer a `GeneIdRefusal`; its
  `payload` is the tool error they answered before.
- A list longer than its bound raises `TooManyIdsError` (a `ToolError`, with `named` and
  `bound`) before any request.
- A gene record read that WDK answers 404 (`gene_models.gene_record`, which every gene
  read goes through) asks `require_gene_records` (`veupathdb_mcp.catalog`) whether the
  site lists the `gene` record type (`GENE_RECORD_TYPE`), and raises
  `NoGeneRecordsError` when it does not. So on OrthoMCL the first id of a lookup, and
  `record_rows`, `record_proteins` and the audit checks, refuse by name where they raised
  a bare `WDKError`. `found_row` reads a 404 as an absent record only when the site lists
  `gene`. The served resolve answers the refusal as a tool error.
- What the check costs: nothing on a read WDK answers. On a 404, the site's catalog when
  the process holds it (no request); otherwise one unexpanded `GET /record-types`,
  held per site for the life of the process. No catalog is loaded or built for it.
- `one_list_rows` is gone. `upload_gene_list(site_id, gene_ids)` uploads the id-list
  dataset and answers a `GeneListDataset` (`siteId`, `datasetId`, `size`) a host stores;
  `read_gene_list(dataset)` reads its `GeneByLocusTag` report under the account that
  uploaded it. A read retried after a failure takes the stored reference and uploads no
  second dataset. An empty list is refused before an upload. With veupathdb-py 0.1.0b22
  the upload POST itself is sent once: a 502 to it is not retried
  (`test_an_upload_the_site_answers_502_is_sent_once`).
- Requests per id are unchanged from b38: one gene record read, then for an id no record
  names one `GenesByText` search and one record read per matched gene, all sequential.
- `scripts/record_orthomcl_gene_class.py` records QA OrthoMCL's `GET /record-types` and
  one `gene` record read (two requests, no dataset) into
  `tests/unit/catalog/fixtures/orthomcl_gene_class.json`. Until it runs, the OrthoMCL
  tests skip with `NEEDS_QA_RECORDING`. The hermetic suite serves plasmodb's record types
  from the client's QA recording (`record_types`) and fails a test that asks any other
  site's.
- What a host does to take this release: call `read_each_gene_id` where it needs a
  verdict per id, catch `TooManyIdsError` and `NoGeneRecordsError`, and replace
  `one_list_rows` with `upload_gene_list`, storing its answer, then `read_gene_list`
  under the same account. It pins veupathdb-py 0.1.0b22.
- `DiscoveryService.held_record_types(site_id)` answers the record types of a catalog the
  process holds, or None, and never loads one. The gene-class check reads it in one step,
  so an eviction between a look and a read cannot start a catalog build.

## 2026-10-23 - 0.2.0b38

- `resolve_gene_ids_to_records` reads each named gene by its own gene record
  (`read_gene_ids`, `veupathdb_mcp/gene_lookup/records.py`, over `rows_named`), with the
  text-search fallback for an id no record names, at most `RECORD_READS_PER_CALL` (80)
  ids a call, and writes nothing into the account. `lookup_gene_records` fills a hit that
  lacks an organism or a product from the same reads. Both were annotated read-only and
  each uploaded an id-list dataset. The result keeps its shape; `previous_ids` is now
  empty, because only the transcript report the dataset path read serves
  `gene_previous_ids`. The served resolve no longer takes `record_type`, `search_name`
  or `param_name`, which only the dataset path read. Its schema and description state
  the bound of 80, and its description says that one id naming several genes, holding a
  wildcard or a space, or matching more than 50 transcripts makes the call answer an
  error and no records. Both lookups declare `AUDIT_MAX_CALL_SECONDS` (120), because
  80 ids are 80 to 160 sequential requests where the old path made 2.
- `enrich_gene_ids`, `run_control_tests_on_search`, `run_control_tests_on_step` and
  `create_gene_set_step` keep their dataset, and each description says the call writes
  one dataset into the calling user's WDK account, which WDK cannot delete.
  `test_every_dataset_write_is_described.py` runs every served tool on its recorded or
  faked site with the upload refused, and holds the tools that reach it equal to the tools
  whose description says so.
- `TRANSCRIPTS_PER_GENE` and `dataset_client` move from `veupathdb_mcp.gene_lookup` to
  `veupathdb_mcp.wdk`, so the lookup can read through the audit's record reads without an
  import cycle. `veupathdb_mcp.gene_lookup` publishes `read_gene_ids`.
- `lookups_pfal3D7.json` was recorded on QA plasmodb on 2026-10-23 by
  `scripts/record_gene_lookups.py`, under the test account, one request in flight, with
  every dataset upload refused: 4 WDK requests (1 user read, 3 gene record reads), no
  dataset, no status of 400 or more. `PF10_0316` resolves to `PF3D7_1032400`.
- What a host does to take this release: read `TRANSCRIPTS_PER_GENE` and
  `dataset_client` from `veupathdb_mcp.wdk` if it reads them, and call `read_gene_ids`
  where it resolves ids for a chat and wants no dataset written. `resolve_gene_ids`, the
  id-list read, is unchanged. It pins veupathdb-py 0.1.0b21, as 0.2.0b37 did.

## 2026-10-22 - 0.2.0b37

- 0.2.0b37 serves the gene models of the genes a check judges, in genome coordinates:
  `ModelSpans` (gene, transcript, seqid, strand, exon and CDS spans of the transcript the
  coding parts take) and, for a merge, `GeneSpan`. `IntronAudit.model`,
  `GeneLengthAudit.models`, `PseudogeneCallAudit.referenceModel` and
  `StrainModelAudit.models` come from the `GeneModelDump` reads the checks already made;
  `GeneFusionAudit.models` and `.merged` and `SelenoproteinEndAudit.models` add reads.
  Every new field defaults to none read, so a result stored before 0.2.0b37 validates.
  Each result refuses models of genes it does not judge.
- New reads, one gene record read each, made by `ModelReads`, which refuses a third read
  in one call (`MODEL_READS_PER_FINDING` = 2): the reference of a strain whose genome was
  read (1), the reference and the partner of a LONG gene's fusion (2 at most), and the
  reference of a selenoprotein end (1). The selenoprotein check's organism read of its gene
  now asks for the model table too, the same request. `ModelRow` reads `sequence_id` and
  `strand`.
- A gene model whose table gives no CDS row, no Exon row for its transcript, or rows on
  two sequences or strands is null in the result's models, and `evidenceUnread` gives one
  reason for each null model (`ReadModels`); the check judges as it did at 0.2.0b36. Two
  refusals of 0.2.0b36 stay: the intron check refuses a model with no Exon row for the
  transcript it judges, and the pseudogene check refuses a reference with no CDS.
- The fusion check reads its reference's neighbours' proteins by record
  (`record_proteins`, two record reads per neighbour, at most 6 neighbours) and uploads no
  gene list; it used `proteins_of`, which uploaded one.
- `fusion_pfraNilgiri_rpt6.json` was re-recorded on QA plasmodb on 2026-10-22 by
  `record_audit_fusion.py`, which reruns the check with every gene list upload refused:
  22 record and report reads (17 gene and transcript record reads for rows and proteins,
  1 Orthologs read, 2 genome reports, 2 model reads), no dataset, no status of 400 or
  more. The recorded test replays it read by read.
- `build_every_species_expression` writes one unit `S>=ceil(k/2)T` per species: a group
  is present in a species of k genomes when at least ceil(k/2) of them hold a protein.
- The strain recorder keeps only `--models`, which adds gene model reads by single gene
  record reads; its full mode uploaded gene lists as datasets and is removed. The fusion
  recorder's full mode reruns the check by record reads with every dataset upload refused.
  `test_recorders_upload_no_dataset.py` runs the strain, fusion and selenoprotein recorders
  with the dataset upload refused. Five older recorders still upload datasets:
  [every recorder reads by record and uploads no dataset](backlog/every-recorder-reads-by-record-and-uploads-no-dataset.md).
- 0.2.0b37 also serves `build_every_species_expression`
  ([a search note fills only an empty description](decisions/a-search-note-fills-only-an-empty-description.md)).
  It pins veupathdb-py 0.1.0b21, as 0.2.0b36 did.
- Recorded on QA on 2026-10-22, under the test account, one request in flight, no
  dataset: the selenoprotein tool's wire at 0.2.0b36 (`selenoprotein_tgonGT1_selk.json`,
  7 gene and transcript record reads and 3 JBrowse store reads), then 6 `GeneModelDump`
  record reads added to the strain, fusion and selenoprotein wires, and one OrthoMCL
  count report for Cryptosporidium. No status of 400 or more.
- What a host does to take this release: read the new result fields, count the model
  reads above in its request estimates, and give the every-species builder to whatever
  writes phyletic expressions.

## 2026-10-22 - 0.2.0b36

- 0.2.0b36 reads every gene a served check names by its own record, so no tool a chat
  calls uploads a gene list, reads an ortholog group from the one `Orthologs` table
  read, gives a host one id-list read per run, and stages the intron check's evidence
  ([a named gene is read by its record](decisions/a-named-gene-is-read-by-its-record.md)).
  It pins veupathdb-py 0.1.0b21 for the bigWig reader and its total summary, the JBrowse
  request observer and `TabixReader.chunk_group_count`, and no module or test reads a client name off a file
  inside a client package any more.
- Recorded on QA on 2026-10-22, under the test account, one request in flight: 158
  observed WDK requests and 96 JBrowse store reads, no dataset. The recording stopped at
  the first refusal, the 404 the gene record of `PF3D7_1032400.1` answers. A second
  recording, of 175 store reads (the agamPEST rnaseq track list, 168 stranded bigWig
  headers and 6 depth reads), and a third, of 26 store reads over the six shortlisted
  subtracks, with no WDK request, measured AGAP003685's coverage choice.
  `records_pfal3D7_piga.json` holds the gene record, protein and alias reads of PIGA;
  `introns_afumAf293_afu8g00850.json.xz`, `introns_agamPEST_agap007279.json.xz`,
  `introns_tgonME49_tgme49_224540.json.xz` and `introns_agamPEST_agap003685.json.xz`
  hold, xz-compressed, each intron case's record reads and exactly the JBrowse store
  reads the check makes;
  `introns_pcynM_pkac_proteins.json` and `introns_afumAf293_dmaw_proteins.json` hold
  the ortholog proteins the older intron recordings lack.
- The intron check gains `REPLACED`, `NONCANONICAL` and `RETAINED` outcomes and
  verdicts, `motif` and `depth` (median depth, covered share) on an unread intron and
  `evidenceUnread` on the answer. A motif with a base other than A, C, G or T is an
  assembly gap, left unread. The coverage experiment is chosen per gene among the three
  stranded pairs that cover the most bases by bigWig total summary
  (`COVERAGE_HEADERS_READ` 200 header reads per organism and process,
  `COVERAGE_CANDIDATE_PAIRS` 3), by the highest exon median over the gene.
  Every correctable outcome is corrected and judged by orthologs: up to 16 named per
  call (`ORTHOLOG_PROTEINS_READ`), where 60 were before.
- The strain check places the strain's other group members with one range read of
  the organism's `annotated_transcripts` GFF over the window (`ANNOTATION_MAX_GROUPS`
  4), recorded on QA on 2026-10-22 for both strain cases (one track list and one
  range read each, no WDK request), so it reads no member's record. Every intron evidence stage names a refused read in
  `evidenceUnread` instead of failing the call; concurrent checks of one organism share
  its track list and coverage choice, and a refused RNA-seq track list is read again
  by the next gene, waiting `TRACK_LIST_RETRY_SECONDS` (600) after `TRACK_LIST_TRIES`
  (2) failures; `STRAIN_STORE_READS` (5) names
  a strain call's store cost; at most `JUNCTION_TRACKS_READ` (4) junction
  tracks are read; a peptide clears only an intron the junctions leave unexplained; and
  an ortholog protein is chosen only among members the table gives a length. The judge
  moved to `audit/intron_judge.py`, the coverage reads to `audit/intron_coverage.py`
  and the shared track reads to `audit/track_reads.py`.
- `catalog_record_type`, the catalog's search lookup by context (renamed from
  `find_record_type_for_search`, which `catalog/record_type_resolution.py` keeps),
  answers None for a search the catalog does not list,
  never the record type it was asked under; `resolve_search_record_type`, the parameter
  reads and both control runs refuse such a search with `UnlistedSearchError`, and
  `inspect_search` answers `UnknownSearchError` naming the listed searches. The other
  resolver in `catalog/record_type_resolution.py` loses its two options, which its one
  caller always set.
- The OrthoMCL count recordings are package data under `veupathdb_mcp.testing`
  (`ORTHOMCL_COUNTS`), so a host's suite reads them from the installed distribution.
- What a host does to take this release, beyond the pin: read an ortholog group as
  `OrthologGroup.members` (`GroupMember`), which no longer holds the gene itself or a
  location; pass members to `call_length`, `classify`, `closest_reference`,
  `relatives_of` and `relatives_median`, and the placed genes and the members to
  `GroupProfile.of`; read named genes with `record_rows` and `record_proteins` (at most
  80 per call) and a run's list with `one_list_rows` (at most 400 ids, one dataset,
  `LIST_MAX_PAGES` report pages); build members from genome rows with
  `GroupMember.of_row`, which keeps the coding rule and leaves `syntenic` and
  `referenceStrain` unknown;
  stop reading `INPUT_ID`, `LOCATED_ATTRIBUTES`, `ORTHOLOGS_READ`, `gene_rows` and
  `ortholog_species`, which left the surface; handle None from
  `catalog_record_type`; and accept `evidenceUnread`, `motif` and
  `depth` and the three new verdicts in an intron answer.

## 2026-10-22 - 0.2.0b35

- 0.2.0b35 serves `build_protein_count_comparison` and `build_clade_only_expression`, rewords the `GroupsBySingleCopy` note and
  adds the complement recipe to the `phyletic_expression` help
  ([a search note fills only an empty description](decisions/a-search-note-fills-only-an-empty-description.md)).
  It pins veupathdb-py 0.1.0b18, as 0.2.0b34 did.
- `build_protein_count_comparison` takes two single genome codes of the OrthoMCL taxonomy,
  reads K, the smallest count at which `B>=K+1` answers no group, by bisection over count
  reports, and returns the ladder `B=0 AND A>=1 OR ... OR B=K AND A>=K+1` with the groups it
  answers, its length and K; `reverse` adds the opposite ladder, which stops at K - 1. One
  call sends at most 15 count reports, each with no records, one after another, and declares
  a 120 second call budget. A clade code, an unknown code or one genome named twice is refused
  before any report, and a genome B with 1024 or more proteins in one group is refused after
  the fourth probe, because its ladders would not finish within the budget. The two-genome
  recipe of the help names the tool.
- The tool's tests replay the QA OrthoMCL build 8.2 recording of 2026-10-21
  (`tests/unit/catalog/fixtures/orthomcl_protein_count_ladder.json`): the eight bisection
  probes in the order the tool sends them, and the totals of both ladders. The ladders were
  sent with each AND term in parentheses, which the site reads as the same query, so the
  replay compares the site reading of each expression, unit by unit and in any code order.
  Two more recordings (`orthomcl_protein_count_ladder_osat_zmay.json`, `..._zmay_osat.json`)
  hold the large-family pair below: its probes verbatim, and the ladders rebuilt by the tool's
  own rule, whose lengths equal the logged lengths of what was sent. The result validates its own dump
  (`tests/unit/test_served_results_round_trip.py`).
- The `GroupsBySingleCopy` note no longer compares the search to `GroupsByGenomeCount`. It
  states what the search returns, that it does not limit the proteins of one genome and that
  an answer from it states that limit, names `L=NT AND L=N` for single copy over named
  genomes, and states that the three ranges apply together, so an all-genome range above the
  sum of the core and peripheral maxima returns no group.
- The help states presence only in a clade L as `L>=1T AND C=0T`, C every genome outside L,
  names `build_clade_only_expression` to build it, and states absence from a named clade X as
  `L>=1T AND X=0T` (X, because M is the clade `within` names). `test_the_help_recipes_parse.py` passes both through the served validator
  (C of 855 codes) and the client's evaluation.
- `build_clade_only_expression` takes L as a clade code or the genome codes of a group with no
  clade code, and optionally `within`, a clade M that holds L. It writes C, the genomes
  outside L (or outside M), as the fewest taxonomy codes that cover them, sends one count
  report, and returns the expression, the groups, its length, the genome codes of L and the
  number of genomes C covers. An unknown code, an empty or genome-less L, an L that covers
  every genome and an M that does not hold L are refused before the report. Its tests read
  the client's recorded taxonomy, pass each expression through the served validator and the
  client's evaluation, pin that a clade with no genome is never written and that codes under
  a named clade collapse into it, and replay three recorded counts
  (`orthomcl_clade_only_counts.json`): a clade-only expression measured on 2026-10-21 in
  another code order and the two smoke counts below, the last
  rebuilt from the recorded taxonomy, whose first 200 characters and length equal what was
  sent.
- Live on QA OrthoMCL with this release's source, anonymous, one request at a time: 15
  requests, all 200 (the service root, `/app`, the taxonomy and 12 count reports). The
  comparison of the recorded genome pair reads the K and the two ladder totals of the
  recording in 10.2 s: 8 probes of 0.23 to 0.27 s and ladder counts of 4.0 and 4.3 s. A
  clade-only count over a clade code took 5.2 s and over a genus list 4.8 s.
- Live on QA for a large family, the same way: 27 requests, all 200. `osat` over `zmay`
  bisects `zmay` in 11 probes to K = 340 and counts 13,354 and 11,130 groups in ladders of
  8,644 and 8,618 characters (10.5 and 11.6 s), 25.6 s in all; `zmay` over `osat` bisects
  `osat` in 9 probes to K = 212 and counts the same 11,130 and 13,354 (5,316 and 5,290
  characters, 9.1 and 8.7 s), 20.2 s in all. Both directions agree on both totals.
- The budget: a ladder count grows with its length, at 32 to 42 ms per term measured. 120 s
  is 4.7 times the slowest measured call (25.6 s), and covers the estimate at the largest K
  the tool accepts, 1,023: about 2 x 1,024 x 0.042 s for the two ladders and 13 x 0.3 s for
  the probes, about 90 s. A larger K is refused by name rather than left to time out, which
  also lowers the request bound from 29 to 15. The clade-only builder sends one report
  (4.8 to 5.2 s measured) and keeps the default budget.
- What a host does to take this release: expose `build_protein_count_comparison` and
  `build_clade_only_expression` to the agent that writes phyletic expressions, in the same
  change as the pin, because the help names both tools; a host that lists sample arguments
  per served tool adds theirs.

## 2026-10-22 - 0.2.0b34

- 0.2.0b34 ships served results that validate their own dump
  ([a served result validates its own dump](decisions/a-served-result-validates-its-own-dump.md))
  and pins veupathdb-py 0.1.0b18, as 0.2.0b33 did. `Linkout.external_id` dumped
  `externalId` and read only `ext_id` or `external_id`, so the recorded PIGA, K13, GLO1
  and DMAW evidence, with 11, 43, 7 and 26 cross-references, failed to read back with one
  error per cross-reference. The NF54 provenance failed on `recordId`, `referenceStrain`
  and `ncbiTaxon`, and `referenceStrain` then on its dumped `false`. Each of these
  fields now reads its camelCase alias too, and `referenceStrain` reads a boolean.
- `tests/unit/test_served_results_round_trip.py` walks the return type of every tool of
  both servers (102 models) and replays the recordings of thirteen gene-model tools; no
  other model dumped a key it did not read.

## 2026-10-22 - 0.2.0b33

- 0.2.0b33 ships the entry below, the control runs that delete every step and strategy
  they write, the measured note for `GroupsBySingleCopy` and the recipes of the
  `phyletic_expression` help
  ([a search note fills only an empty description](decisions/a-search-note-fills-only-an-empty-description.md)),
  and the genome count of each `lookup_phyletic_codes` match with the species its genome
  matches fall in. It pins veupathdb-py 0.1.0b18, whose taxonomy nodes state `clade` and
  whose tree groups genomes by species.
- Live on QA with this release's source and no embedder (56 WDK requests, no embedding
  request): on orthomcl a clade lookup answers the clade with its genome count, a genus
  lookup groups its genomes by species as the recorded taxonomy does, and the listing,
  the index text, the overview and the definition of `GroupsBySingleCopy` carry the note.
  `OG8_0003303` reads as 736 genomes and 1,068 proteins, its `number_of_members`. QA
  orthomcl serves no `dataset` record type: the dataset report answers 404 and the
  catalog build holds no experiments.
- On QA plasmodb, a control run on the first leaf of a three-step strategy (312 genes,
  315 transcripts) files one positive control as recovered and one negative as excluded,
  as the step's answer holds them. `duplicated-step-tree` answers
  `{"stepTree": {"stepId", "primaryInput": {"stepId"}, "secondaryInput": {"stepId"}}}`,
  a leaf with no input keys; the run deletes the two copies outside the leaf, and the
  strategy delete removes the copy, the controls step and the combine, each answering 404
  after it. The strategy list then holds no internal strategy. `get_step_gene_ids` on a
  step of 783 genes is refused by name after one step read and one report of 201 records.

## 2026-10-22 - A step read is bounded by its caller

- `group_genome_counts` reads an OrthoMCL group's `TaxonCounts` table as proteins per
  genome. `fetch_gene_ids_from_step` and `resolve_wdk_context` take a required record limit
  and raise `StepTooLargeError` past it, so no step read asks for every record. See
  [a step read is bounded by its caller](decisions/a-step-read-is-bounded-by-its-caller.md).

## 2026-10-21 - 0.2.0b32

- 0.2.0b32 ships the two entries below, the gene-id resolver and the ten new gene-model
  tools, and pins veupathdb-py 0.1.0b17, whose tabix reader the intron check reads
  junctions with.
- The missing-gene check reads the anchor's genome key with `gene_organism`
  (`organismAbbrev`, no table). `missing_tgonGT1_nac.json` is recorded again on QA
  toxodb (13 WDK requests); only that record read changed, and the answer stays
  `IN_DNA_UNANNOTATED`, 34 of 34 windows.
- The genome pseudogene-call description builds its word list from `FAMILY_WORDS`, so
  the two cannot differ.
- Live on QA plasmodb with this release's source: the NF54 CM019798.1 contig against
  PF3D7_MIT02300 answers `SPLIT_AT_JOIN` (274 on the line, 376 on the circle, an
  87-base end overlap); PfDd2_140076300 against PF3D7_1472100 loses 271-310,
  `GENOME_ENCODES`, side `UNCLEAR` with a relatives median of 309; PcyM_0736700 answers
  `UNSUPPORTED_MISSING_EXON` with corrected parts of 124, 158, 185, 160 and 399 bases
  and 1970 best junction reads; the genome priority ranks 63 genomes, NF135.C10 sixth
  at a gap of 5.4.

## 2026-10-21 - The audit resolves a gene id and judges only what it was asked

- Every gene-model tool that takes gene ids resolves each through the site and serves
  `geneIds`, the id given beside the gene id it resolved to; every other gene field is
  the resolved id, and an answer whose gene fields differ from them is invalid
  (`veupathdb_mcp.audit.gene_ids`, `served.located`). The row read asks
  `GeneByLocusTag` for `input_id`, which echoes each input that matched a transcript,
  and every id takes only the genes echoed for it (its own id first). An id with no
  echoed row goes to `GenesByText` on primary keys only, over every organism the search
  lists (read once per site), and takes the one gene whose own id, without its `:` qualifier, is the id; an
  id with `*` or a space, an answer over 50 transcripts and an id that names several
  genes are refused. On QA plasmodb `PfNF54_100037200` beside `PF3D7_1032400` echoes
  only PIGA and the text search names `PfNF54_100037200:pseudogene`
  (`gene_ids_pfalNF54_piga.json`, `record_audit_gene_ids.py`); `resolve_gene_ids` does
  not resolve it. The evidence tool now reads the gene's row first, and the missing-gene
  tool resolves its example gene.
- The row-read recordings were taken again with `input_id`
  (`pcynM_pkac_length.json`, both `strain_*`, both `introns_*`, both `fusion_*`,
  `missing_tgonGT1_nac.json`, `organelle_pfal3D7_cytb.json`); each equals its old
  version as JSON apart from `input_id`, with its key order moved. The organelle recorder
  also rewrote the five `organelle_*_mito.json` contigs, which equal their old versions
  as JSON.
- A site failure is labelled from the error the client raises: an HTTP status (WDK
  cause or `JBrowseError.upstream_status`) reads "<site> answered <status> to the audit
  reads: <detail>" (and "to the ortholog reads" in the intron check), a timeout or a
  failed connection "did not answer".
- A report served short of its total (`genes.complete_answer`) raises
  `DataParsingError` naming the search and both counts, not `WDKError` with status 502:
  it is a data fact, and a caller that retries outages does not retry it.
- `gene_organism` reads a gene record's `organismAbbrev` and no table; the pseudogene
  check's strain gene and the selenoprotein's gene use it. The anatomy reads each gene
  record once and the strain window once, sharing `pseudogene_pair` and
  `pseudogene_dna` with the pseudogene check: two record reads where it read four, and
  one strain window where it read two.
- The selenoprotein check reads both genes' rows and proteins in one `GeneByLocusTag`
  report (`rows_and_proteins`). `proteins_of` takes the lowest transcript id on an exact
  length tie; the one recorded tie (BDCG_01190, four 436-residue transcripts) holds one
  sequence, so no recorded answer changes.
- `STOPS_AT_SEC` needs `secAligned` (the model's last residue, projected along its last
  identical block within 3 residues, falls on the residue before the reference's first
  U) and `tailIdentity` 0.8 or more; a TGA after a model
  that ends elsewhere is `NOT_AT_SEC`. The recorded GT1 SelK stays `STOPS_AT_SEC` (1.0,
  aligned) and ME49 SelK `CONTAINS_SEC`.
- The pseudogene check and the anatomy refuse a strain gene the site does not flag as a
  pseudogene, naming the gene and its flag; the recorded NF54 PIGA stays `INTACT`.
- A split pair is judged only when the two genes are the only coding members of the
  group in their organism; three members give no pair.

## 2026-10-21 - Ten more gene-model tools are served

- `audit_strain_model`, `audit_missing_gene`, `audit_organelle_gene`,
  `audit_pseudogene_anatomy`, `audit_genome_pseudogene_calls`, `audit_intron_support` and
  `audit_gene_fusion` are served read-only with the 120 s audit budget; `audit_genome_priority`,
  `audit_gene_evidence` and `audit_genome_provenance` are served read-only with the
  default budget
  (`decisions/an-audit-check-reads-its-genome-from-the-site.md`). Every tool that names
  an organism takes its full name.
- `audit_strain_model` serves check 4, a strain's gene model against its species
  reference: lost and extra runs, the strain's genome read for a lost run unless the
  group is residual or another group member lies in the window, the relatives it
  compares with, and a side judged only where the strain's genome encodes the lost run.
  Recorded on QA plasmodb: PcyM_0736700 against PCYB_074210 lost 41-100 and its genome
  encodes it (no side: 8 copies per organism); PfDd2_140076300 against PF3D7_1472100
  lost 271-310, encoded, side unclear (40 relatives, median 309).
- `audit_gene_fusion` serves check 3, a `LONG` gene against its closest single-copy
  ortholog: the extra runs of its protein, the neighbour of the reference within 3 genes
  on its sequence that holds the most extra windows (`EXTRA_MATCHES_NEIGHBOUR` at 3
  windows and 40%: a protein fact, with no claim about how the model was built), and
  for a match the models of that neighbour's group beside the gene. Only a
  match names a `partner` (with its group and product); an unexplained answer names its
  `closestNeighbour`. A gene of
  any other class answers its class and reads nothing more. Recorded on QA plasmodb
  (`scripts/record_audit_fusion.py`, every read in order, each genome report trimmed to
  the gene, 4 genes on each side and the nearest gene of another sequence, so the
  recording pins the reach of 3 and the sequence filter): AK88_02763 against
  PCOAH_00051830 is
  `EXTRA_MATCHES_NEIGHBOUR` with PCOAH_00051820, 56 of 66 windows, no separate model beside it;
  on QA toxodb TGME49_500302 is `UNQUALIFIED` (two copies per organism in its group) and
  no protein is read. The length screen is public as `served.length_screen`, and the
  missing-gene wire replay takes a list of calls so both recordings replay through it.
- The length check's genome read takes the window and the proteins its caller holds
  (`length_window`, `length_dna`, `length_flank`, `read_proteins`), so a strain check
  reads its two proteins once. `relatives_of(reference, model, rows)` names the
  relatives and their tier, and `relatives_median(reference, model, rows)` stays
  published as their median; both leave out the organisms of the reference and of the
  audited model (reference P. vivax 319, model P. knowlesi 110, P. falciparum 300 and
  two other genera at 310 and 312 give 311.0, where counting the model gave 205.0).
  The recorded YIP1 side stays `UNCLEAR` at 309 and PKAc `NO_RELATIVES`.
- `audit_missing_gene` finds two anchors around an example gene whose `OG` ortholog
  groups have one gene each in the absent genome, reads the DNA between them with the
  code inferred from the example's CDS, and answers whether it holds the example
  protein (`IN_DNA_UNANNOTATED`, `IN_DNA_OTHER_MODEL` with the overlapping models'
  pseudogene flag, `GAP`, `PARTIAL`, `NOT_IN_DNA`, or `NO_SYNTENY` with no genome read
  and no genome fact served), with the stops inside the stretch the found windows cover
  and whether one frame holds the protein without a stop.
- `audit_organelle_gene` resolves the genome key from the first protein-coding gene on
  the named sequence, reads the whole contig, joins the longest end overlap of 20 bases
  or more whose two copies agree at 99% of positions once (`overlapBases`,
  `overlapMismatches`), and asks whether one open frame holds 95% of a reference
  protein on the contig as stored (`INTACT_ON_THE_LINE`) or only on the circle turned
  by half its length (`SPLIT_AT_JOIN`), with the code inferred from the reference
  gene's CDS. NF54, 7G8 and 7G8 2019 CYTB read `SPLIT_AT_JOIN` (7G8's 127-base end
  overlap has one differing base).
- `audit_genome_priority` ranks a site's genomes by the gap between their BUSCO genome
  and protein completeness, largest first. The organism's full name is
  `organism_full`; the record id `source_id` is a taxon id (`NCBITAXON_36329`,
  `TMPTX_pfalNF135C10`), not the organism abbreviation.
- `audit_pseudogene_anatomy` states a pseudogene's `Exon` segments; for each junction
  the gap, the gap modulo 3, the longest single-base run within 5 positions of either
  gap end and the Ns within 100 positions; the gene's contig distances and Ns; the
  reference's `Exon` count; and the pseudogene check of the genome window.
- `audit_genome_pseudogene_calls` (named apart from the one-gene
  `audit_pseudogene_call`) pairs each pseudogene of a genome with one single-copy coding
  reference gene, by ortholog group first and by identical product otherwise; a product
  that holds a word of `FAMILY_WORDS` does not pair. A coding reference gene is flagged
  not pseudo, protein-coding (`is_coding`) and in an `OG` group that is not residual
  (`is_orthology_group`). `basis` is `ORTHOLOG_GROUP` or `PRODUCT`, and `unpairedGenes`
  names every unpaired pseudogene with its reason and, for a listed word, the word. QA plasmodb serves no ortholog group
  for a pseudogene ("N/A (orthology not determined for pseudogenes)"), so P. falciparum
  calls pair by product, and no recording yet exercises the ortholog-group step on
  served rows. On the recorded NF54 and 3D7 reports the rule gives 26 calls of 229
  pseudogenes; 160 hold a listed word, 35 have no coding 3D7 gene with their product and
  8 a product that several hold. The answer counts the genes whose pseudogene flag the
  site does not serve, and says when the genome flags none of its genes.
  `rate_with_bounds` states a rate with its Wilson interval, floor and ceiling.
- `audit_gene_evidence` returns a gene's transcripts, PDB similarities (one per
  structure, its chains, identity, the site's protein-covered percent and e-value; no
  positions are served), mass-spec peptides with their positions on their transcript
  (from `MassSpecDownload`), AlphaFold models, cross-references, sequence edits, the
  counts of user comments, PubMed articles and notes, the phenotype tables named for
  the gene's organism with their rows, the phenotype tables named for no organism apart
  (`unprefixedTables`), and the tables the site does not serve.
  `audit_genome_provenance` returns an organism's genome source and version, annotation
  source and version, genome date and builds from the organism report.
- `audit_intron_support` judges every unread annotated intron of the longest-CDS
  transcript against every RNA-seq junction track of the organism, and serves the
  corrected model when strong junctions explain them all. On QA, PcyM_0736700 answers
  `UNSUPPORTED_MISSING_EXON` with the corrected CDS [124,158,185,160,399] (341 aa) and
  Afu2g18040 `UNSUPPORTED_SHIFTED` with 459 aa. A gene whose every annotated intron is
  unread is judged when a Strong Evidence junction of 50 reads or more lies inside it on
  its strand; the prototype skipped it. A gene with a read annotated intron keeps the
  prototype gate (best annotated intron, 50 reads). The RNA-seq junction model is
  `RnaJunction`. The check reads junctions with the client's tabix reader
  (`TabixReader`, `SequenceNotIndexedError`, `parse_gff_line`): the pin moves to
  veupathdb-py 0.1.0b17.
- `GenesByLocation` reads only some genomes of a site: on QA toxodb its organism
  vocabulary holds the 8 chromosome-level genomes, and on QA plasmodb it lacks
  P. falciparum NF54, 7G8 2019, NF135 and NF166; any other organism answers 422.
  `GenesBySequenceSourceId` answers 500 on QA toxodb. No served check calls
  `genes_in_region`, and it is removed with `region_answer`; the missing-gene,
  organelle, genome pseudogene-call and gene-fusion checks read whole genomes with
  `GenesByTaxon` (`genome_answer`), parsed in a worker thread.
- One reader serves the site's organism records (`organism_report`, `GenomeDataTypes`)
  to the genome priority and the provenance, and one per-site, per-process read of the
  gene record type (`veupathdb_mcp.wdk.gene_record_type`) serves the evidence tables and
  the expression summary's key columns.
- `gene_models.longest_transcript` picks the rows of the transcript with the largest
  summed length for any row type: `coding_parts` reads `CDS` rows with it and the
  anatomy reads `Exon` rows. `lengths.is_orthology_group` (an `OG` group that is not
  residual) is the one orthology rule of the anchors, the pseudogene pairing, the
  fusion copies, the length screen and the intron ortholog count;
  `lengths.is_residual_group` names the residual case the strain check serves. A strain
  pair under an `N/A` label is refused. `lengths.is_coding` is the coding rule of the
  length statistics, the pseudogene pairing's reference genes and the organelle's first
  coding gene.
- The helpers the checks share are public: `served.located`, `window_refusal`,
  `coding_dna`, `read_proteins`; `audit_tools.run_in_a_slot`, `read_inputs`,
  `audit_slots`; the recorder's `served_body` and `served_answers`.
- `gene_models.transcript_spans` and `ModelTable` are the one reading of a transcript's
  rows and of the `GeneModelDump` table, and `model_record` is the one read of a gene's
  model record for `gene_model`, the anatomy and the intron check.
- `audit_gene_fusion` answers `EXTRA_MATCHES_NEIGHBOUR` (constants `NEIGHBOUR_WINDOWS`,
  `NEIGHBOUR_SHARE`): the model's extra residues match the protein of the neighbour
  `partner` names, a protein fact with no claim about how the model was built.
- `audit_missing_gene` answers `ANNOTATED_IN_GENOME` when the absent genome annotates
  genes of the example's `OG` group anywhere, the syntenic locus included
  (`annotatedMembers`: id, sequence, start), and reads no other genome and no DNA. An
  answer that reads no genome serves `overlapping` null and `codeInferred` false, as the
  other audits do.
- `audit_intron_support` keeps its judgement when the correction's protein or window
  cannot be read and says why (`correctionReason`); `NOT_EXPRESSED` serves `unread`
  null, `NOT_CHECKED` serves `introns` and `unread` null, and `tracksRefused` names
  every refused track when no track indexes the sequence and is null when no track was
  read. Every recorded intron number stays.
- `audit_genome_priority` serves `{siteId, genomes}`; `audit_strain_model` serves its
  relatives' median once, as `relatives.median`. The pseudogene-call, selenoprotein-end
  and anatomy descriptions say they read the standard code; the provenance description
  names every served field; the anatomy description names the transcripts its segments
  and `dnaCheck` come from.
- One `SiteCache` holds a per-site value for a process: the parsed gene record type
  and the `GenesByText` organisms. One tabix reader serves every intron audit on a
  JBrowse client. The organelle check reads only the organism of its first coding gene
  (`gene_organism`). `contig_sides` is the one contig walk of the fusion and
  missing-gene checks, and `length_span` the one window span of the length, split and
  strain reads.
- `covered` and the recorder's region mode (`pfal3D7_piga_neighbours.json`) are
  removed: nothing called them. `rate_with_bounds` stays for PathFinder's audit pass.
- Fixtures written on QA by their recorders: `strain_pcynM_pkac.json` and
  `strain_pfalDd2_yip1.json` (`record_audit_strain.py`); `missing_tgonGT1_nac.json`
  (`record_audit_missing.py tgonGT1_nac`, every read in order, the two whole-genome
  reports trimmed to the records the check reads); `organelle_pfal3D7_cytb.json` and the
  five `organelle_*_mito.json` contigs (`record_audit_organelle.py`); `busco_plasmodb.json`
  and `busco_toxodb.json` (`record_audit_busco`); `anatomy_pfalNF54_piga.json` and
  `anatomy_pfalNF54_pagm.json` (`record_audit_anatomy.py`);
  `pseudogene_calls_pfalNF54.json` and `pseudogene_calls_pfal3D7.json`
  (`record_audit_pseudogene_calls.py`); the `evidence_*.json` record types, gene
  records and organism report (`record_audit_evidence.py`); `introns_pcynM_pkac.json`
  and `introns_afumAf293_dmaw.json` (`record_audit_introns`).

## 2026-10-21 - Two length checks are served

- 0.2.0b31: `audit_gene_length` and `audit_gene_split` are served read-only with the 120 s audit
  budget. Each reads the gene's ortholog group, classes its protein length against the
  genus median of the group, and reads the genome around a `SHORT` or `SPLIT`
  gene for the closest single-copy ortholog's protein
  (`decisions/an-audit-check-reads-its-genome-from-the-site.md`).
- `veupathdb_mcp.audit` publishes the group statistics (`lengths`: `GroupProfile`,
  `call_length`, `Confirmable`, `NotChecked`, `classify`, `closest_reference`,
  `relatives_median`, `species_of`, `genus_of`), the verdict (`length`: `check_length`,
  `DnaWindow`, `LengthCheck`), the reader (`length_inputs`, `LengthInputs`,
  `LengthScreen`, `LengthDna`, `GeneLengthAudit`, `LENGTH_EDGE`, `LENGTH_MAX_FLANK`,
  `SPLIT_MAX_GAP`) and `locus_tag_answers`, the `GeneByLocusTag` reports the gene rows
  and proteins are read from.
- Only a `SHORT` gene or a `SPLIT` pair reads the genome. `TYPICAL`, `LONG` and
  `UNQUALIFIED` answer `NOT_CHECKED` with `nsInWindow` and `atContigEdge` null. A gene
  whose organism holds another member of the group, a split pair that is not two
  adjacent members of the group, and a residual (`OGR`) group are `UNQUALIFIED`.
- The length checks infer the genetic code from the audited gene's own CDS and protein,
  and answer the code and whether it was inferred. The pseudogene and selenoprotein
  checks still translate with the standard code.
- A `SHORT` or `LONG` call needs the genus relatives to agree (each at 0.85 of the
  median or more, or at 1.15 or less), and a group whose median is under 80 residues
  cannot judge. On the recorded PIGA group this makes PCYB_062670 (266 aa) `UNQUALIFIED`,
  because PY03143 is 376 aa.
- `GeneRow.pseudo` is `None` when the site serves no `is_pseudo` value: the site does
  not say. QA plasmodb serves it null for P. chabaudi chabaudi CB and P. vivax-like
  Pvl01 genes, and the strict read refused every ortholog group that holds one. The
  group statistics exclude only rows whose flag is `True`.
- `rows_of(answer, search_name)` refuses a record that is not a gene row with a
  `DataParsingError` that names the search, the record ids and the unreadable fields,
  so a served check answers a named tool error.
- A length answer carries `groupCopies` and `groupSpread` beside `organisms` and
  `groupMedian`, so an `UNQUALIFIED` answer shows why.
- `pcynM_pkac_length.json` is written by `record_audit_fixtures.py length` on QA
  plasmodb and holds the wire bodies: the gene records of PcyM_0736700 with its
  `Orthologs` and `GeneModelDump` tables, the `GeneByLocusTag` reports of the gene and
  of its group (523 genes, 63 organisms), the protein report of the gene and
  PCYB_074210, the contig length and the gene with 30,000 bases on each side.

## 2026-10-21 - The audit infers a gene's genetic code from the site's own protein

- `GeneticCode` adds NCBI table 3 (`YEAST_MITOCHONDRIAL`: TGA W, ATA M, CTN T) and table 5
  (`INVERTEBRATE_MITOCHONDRIAL`: TGA W, ATA M, AGA and AGG S), as NCBI's genetic code page
  lists them.
- `infer_code(cds, protein)` tries STANDARD, CTG_SERINE, UGA_TRYPTOPHAN, table 3 and
  table 5 in that order and returns the first whose translation of the CDS equals the
  served protein, or `None`. The first codon reads as M, one trailing stop codon is
  dropped, a `U` matches only a TGA under a code that reads TGA as a stop, and a CDS
  whose length is not a multiple of 3 infers no code.
- The served checks still translate with the standard code
  (`decisions/an-audit-check-reads-its-genome-from-the-site.md`).

## 2026-10-21 - The audit reads a gene's orthologs and a region's genes

- `orthologs_of` reads the `Orthologs` table of the gene record ("Orthologs and
  Paralogs within this website"), then the rows of those genes and the gene itself with
  `gene_rows`. `GenesOrthologousToAGivenGene` is not a search on plasmodb (404). The table
  is served on plasmodb (57 rows for PF3D7_1032400) and toxodb (19 rows for TGME49_316600).
  `is_syntenic` is `yes` or `no`, and any other value is refused. A table gene that
  `gene_rows` does not return is a refusal that names it.
- `genes_in_region` reads `GenesByLocation` by sequence id: `organismSinglePick` is a
  JSON list of one organism and `chromosomeOptional` is `Choose chromosome`. A gene that
  overlaps an end of the region is in the answer. A start under 1, or an end before the
  start, is refused before any read; an end of 0 is the end of the sequence.
- The two context fixtures hold the bodies as served: the `Orthologs` rows of the gene
  record and the `GenesByLocation` report records.
- `GeneRow.organism` is the transcript attribute `organism_full`. The attribute
  `organism` serves the name in `<i>` markup, so it does not match the organism of an
  `Orthologs` row or a search vocabulary term.
- The published field `GeneModel.organism` is renamed `organism_abbrev`: it holds the
  organism abbreviation of the gene record, and `GeneRow.organism` holds the full name.

## 2026-10-21 - An audit check reads a bounded window in a bounded thread

- 0.2.0b30: each audit genome window is at most `AUDIT_MAX_WINDOW_BASES` (250,000) bases, and a
  longer one is refused before any gene record or genome read, naming the gene, the
  window length and the limit.
- The selenoprotein check runs in a worker thread like the pseudogene check, and a
  process runs at most two audit checks at once on each event loop. A further call
  waits for a slot, and both served rows declare the 120 s budget
  (`decisions/an-audit-check-reads-its-genome-from-the-site.md`).

## 2026-10-21 - Two gene-model checks are served

- 0.2.0b29 serves `audit_pseudogene_call` and `audit_selenoprotein_end`, both read-only,
  on `veupathdb-py` 0.1.0b16. Each reads its inputs from the site the call names and
  refuses an input the site cannot give as a tool error
  (`decisions/an-audit-check-reads-its-genome-from-the-site.md`).
- `veupathdb_mcp.audit` publishes the readers (`gene_rows`, `gene_model`,
  `pseudogene_inputs`, `selenoprotein_inputs`) and the two answers
  (`PseudogeneCallAudit`, `SelenoproteinEndAudit`). `gene_rows` and `proteins_of` share
  one `GeneByLocusTag` reader on the private dataset client.
- Both answers serialize camelCase. Both checks read the transcript with the longest
  CDS. A selenoprotein window is padded past the reference tail, a second selenocysteine
  in the tail reads as a stop, and a reference with none is refused. A pseudogene pair
  over `PSEUDOGENE_MAX_CELLS` is refused, and its served row declares a 120 s budget. A
  site that does not answer is a tool error naming it.

## 2026-10-19 - A separation run reads each search definition once

- 0.2.0b28 takes veupathdb-py 0.1.0b15. `separate` runs inside
  `search_definitions_read_once`, so a run reads each search definition once. A later
  measurement is charged 7 requests (`MEASURE_REQUESTS`), the first measurement 2 more
  (`FIRST_INTERSECTION_REQUESTS`), an assembled tree `2 * leaves + 5` (`confirm_requests`)
  and an enrichment 29 (`ENRICHMENT_REQUESTS`). The recorded run drops the six reads of a
  definition the run already read.
- The catalog keeps sharing one copy of a definition across logins
  (`decisions/the-catalog-shares-a-search-definition-across-logins.md`).

## 2026-10-18 - A separation run is charged what it now sends

- 0.2.0b27 takes veupathdb-py 0.1.0b14, whose site client keeps the user id each login
  token names and each record type's boolean search. A later measurement is charged 8
  requests (`MEASURE_REQUESTS`), the first measurement 3 more (`FIRST_INTERSECTION_REQUESTS`),
  an assembled tree `3 * leaves + 5` (`confirm_requests`) and an enrichment 30
  (`ENRICHMENT_REQUESTS`). The recorded run drops the six requests the client no longer
  sends: three reads of the boolean search and three of the user.

## 2026-10-18 - An excluding search that holds a few positives is subtracted as a branch

- 0.2.0b26: exact mode also subtracts a branch of two measured searches, an excluding
  search less another search or two excluding searches intersected, when the branch holds
  none of the tree's recovered positives. A tie goes to one search over a branch, and a
  branch needs room for both its searches under `MAX_CRITERIA`.

## 2026-10-18 - A separation run's rows name each search and carry the tree

- 0.2.0b25: a `measured` row carries the candidate's `displayName` and `basis`, and the
  `assembled` and `confirmed` rows carry the assembled tree as `tree`, so a host can draw
  what the run builds before the result arrives.

## 2026-10-18 - No test writes the warm catalog cache

- 0.2.0b24: every test run reads and writes catalogs in a temporary directory, so a live
  run's background refresh no longer replaces a file of the `data/catalogs/` snapshot.
  0.2.0b23 shipped the QA PlasmoDB catalog in place of the snapshot's; this release
  restores the snapshot.

## 2026-10-18 - The recordings are QA recordings

- veupathdb-py 0.1.0b13: every recorded body is a QA recording, and `wdk_record` keeps a
  JSON list answer as JSON.
- The fourteen recordings under `tests/unit/` are recorded again on QA and the production
  backup is deleted. QA matches production on the two Pfam refreshes (2441 and 3745
  entries) and on the separation run's 81 requests stage by stage; QA's PlasmoDB publishes
  337 datasets where production published 323, IEDB among them without a type.
- The attributes each site's gene and transcript record types declare are read from
  `tests/unit/fixtures/gene_record_attributes.json`, recorded on QA, so the test that
  checks the sample's attributes no longer waits on the warm cache.
- The live lane acts as the registered account for every check, through the client
  library's `registered_wdk_token` (a named token, or a sign-in): QA refuses an
  unauthenticated search read.

## 2026-10-16 - veupathdb-py 0.1.0b12

- veupathdb-py 0.1.0b12: `run_search_column_report` counts a search's records by each value
  of one column, and `WDKAttributeField.tools` names the column tools an attribute offers.
  This release changes no code here.

## 2026-10-16 - The organism list is read where it lives

`organism_parameter` checks a search's organism values against `GenesByTaxon`, and reads that
search under the record type the catalog lists it under. A search of another record type, a
dataset search for one, is checked like a gene search, and no request names a record type
that has no `GenesByTaxon`.

- veupathdb-py 0.1.0b11: a site-search query is six words at most, the service's limit, so
  the search finder and the gene lookup no longer fall back on a long query.

## 2026-10-15

- veupathdb-py 0.1.0b10: a cleaned value keeps one line per line of the site's text,
  one space between words and no blank line.

## 2026-10-14

- `lookup_phyletic_codes` answers on OrthoMCL as well. A site whose catalog holds
  `GroupsByPhyleticPattern` is looked up in its own taxonomy, read once per site from the
  helper record's two taxon tables, and the hint names `phyletic_expression`; every other
  site still reads `GenesByOrthologPattern`'s tree. Both are one `PhyleticTree`.

- A stated `phyletic_expression` is parsed and its codes are checked against that taxonomy
  before the criterion is accepted, and the value is held in the site's spelling. OrthoMCL
  answers a malformed expression with a 500, so a refusal here is the only readable one.
  The sheet's help states the grammar, including "some but not all of a list"
  (`list>=1T AND list<NT`) and "absent from at least k of N" (`list<=(N-k)T`). A unit
  every group meets or none can, such as `<=17T` over 17 codes, is refused: it states no
  constraint.

- `lookup_phyletic_codes` returns, before its semantic matches and past their cap, every
  entry whose label holds each query word some label holds. A list of strains is only
  usable whole, and a word no label holds, such as "strains", narrows nothing.

## 2026-10-12

- The server holds no VEuPathDB account and the `VEUPATHDB_AUTH_TOKEN` setting is gone. A
  service-mode call reads the paths VEuPathDB opens to a guest as the client library's
  shared guest token, and a path that needs a registered user is refused as
  `WDKLoginRequiredError`. `resolve_gene_ids` raises `WDKLoginRequiredError` before any
  request when the call carries no researcher token.

- An expanded record-types answer that lists no searches for a record type means the type
  has none: the catalog stores the empty list and asks no per-type search listing. A
  listing is asked for only when the answer carries no `searches` at all.

## 2026-10-11

- A page summary's request goes to the address that was checked. The host is resolved
  once, every address must be global, an IPv4 address carried inside a NAT64 or an
  IPv4-compatible IPv6 address must be global too, and the request connects to that
  address with the host's name as `Host` and as the TLS server name. Each request closes its
  connection and starts with an empty cookie jar, so no connection verified for one host and
  no cookie one host set reaches another host on the same address.

- A web result's page summary is read only from a public address. `fetch_page_summary`
  follows a redirect itself, at most five, and checks before each request that the host
  resolves only to global addresses; a loopback, private, link-local or non-http address
  is never requested, whatever the client's own redirect setting.

## 2026-10-10

- A search property every search of a site shares stays out of the indexed text. A site
  sets `organisms` to one value on every search, so it named the same organism on every
  entry and separated none of them; a property whose value differs between searches is
  kept.

- A service token setting that is refused names no secret. A malformed entry is named by
  its position, and a validation error of a token or of the registry carries no input.

- A range parameter binds. A `number-range` or `date-range` parameter with no stated value
  takes the site's default, like the other single-value kinds. A stated value its kind
  cannot read raises `UnreadableValueError`, which names the parameter and its
  `value_format`; before, the value was dropped and the parameter came back as an open slot
  with no options, which no answer could fill. Separation skips such a candidate as
  `unbound_required`.

## 2026-10-09

- An expensive search holds one line on the database
  ([the decision](decisions/an-expensive-search-holds-one-line-on-the-database.md)).
  `veupathdb_mcp.search_line` holds a Postgres advisory lock per site for each High
  Speed SNP search (or each search a host's rule names), the served process installs it
  at startup when it has a database and runs each tool call as one search turn, and
  `count_search_answer` hands its budget to the client, which starts it when the report
  is sent.

- Tests run against QA and a deployment names its site list
  ([the decision](decisions/tests-run-against-qa-and-a-deployment-names-its-sites.md)).
  `tests/conftest.py` puts the client's QA list in force for every test, the fourteen
  recordings made on production moved to `fixtures-production-backup-2026-10-09/`, the
  tests that read them (or the client's moved recordings, or the `data/catalogs/`
  snapshot) are skipped with `NEEDS_QA_RECORDING`, `scripts/record_all_datasets.py`
  records from the QA list only, and `scripts/check-test-sites.mjs` runs in CI and
  pre-commit. Test hosts that are not sites (this server's address, the OAuth server, a
  mailbox) are `.test` or `example.org` names. The WDK admission lane serves the client's
  QA list.

## 2026-10-08

- An open slot carries its whole vocabulary: `_open_slot` and `_contrast_open_slot` kept
  the first 20 values, so the PlasmoDB organism slot ended at `Plasmodium coatneyi` and
  held no `Plasmodium falciparum 3D7` (value 26 of 90), and the VectorBase one held ticks
  only. `resolve_search_parameters` serves each slot through `catalog.shortlist_slot`, the
  rule `build_sheet` uses: whole up to `DIRECT_MAX`, else the `TOP_K` values the criterion
  names best, with the total and the `get_parameter_options` query named in its question.
  The ranking moves to `catalog/shortlist.py`; `catalog.shortlist` and
  `catalog.shortlist_slot` join the surface.
- A filter facet keeps every value the site sent: `filter_fields_for` cut each facet to 12
  values, so the recorded PlasmoDB SNP sample filter offered 101 of 1521 and its country
  facet 12 of 20, without Gambia. `ParameterInfo.filter_leaves` holds them all and
  `facets()` reads them; the contrast slot and the filter clause are built from them. Each
  view a model reads (`filter_fields`, the sheet's `filter_facets`, a read with a query)
  goes through `shown_facets`, the same shortlist ranked by that view's words. A cut facet
  carries `valuesTotal` (537 for the SNP sample name, shown as 200), and the sheet's note
  names the cut facets and the `get_parameter_options` query that reads the rest.
- The web tool asks the deployment's SearXNG, then the engines `ddgs` scrapes. The Brave
  Search API, its key and price settings, and `costUsd` on the web search answer are
  removed ([the reversed decision](decisions/a-keyed-engine-answers-first-and-prices-the-call.md)).
  The scraped `brave` entry leaves `TEXT_ENGINES` too, so no step of the web tool asks Brave.
- Jenkins publishes the two images (`Jenkinsfile`). The research server moved out of
  `Dockerfile` into `Dockerfile.research`, and a release tag is spelled in semver
  ([the decision](decisions/each-image-is-the-last-stage-of-its-own-dockerfile.md)).
  Each file builds the image id its old target built.
- [The image decision](decisions/each-image-is-the-last-stage-of-its-own-dockerfile.md)
  cites pipelib by line: `executeBuild` reads the image keys (lines 193-201), not
  `buildContainers`. The backlog gains
  [the server images install the dev group](backlog/the-server-images-install-the-dev-group.md).

## 2026-10-07

- The AI expression summary is keyed by the gene record's declared primary key columns,
  read once per site from `GET /record-types/gene`: a component site keys a gene by
  `source_id,project_id`, the portal by `source_id` alone, and the reporter refuses any
  other shape with 422. The key always appended the project id, so the portal answered
  422 for every gene. `veupathdb-mcp` is 0.2.0b3 on `veupathdb-py` 0.1.0b3, whose portal
  project id is `UniDB`.

## 2026-10-06

- `veupathdb-mcp` is 0.2.0b2 on `veupathdb-py` 0.1.0b2: a request that makes WDK run a
  search waits for one of a few slots per site and is not sent again after a 5xx or a
  timeout, and every request names its sender in its User-Agent.

## 2026-10-04

- `veupathdb-mcp` is 0.2.0a41. A study runs on the organisms of the dataset record it
  is: `SearchCatalog.study_organisms(dataset_id)` reads the card `study_assay` reads,
  from the `AllDatasets` report the build already posts, and a host reads it as
  `veupathdb_mcp.catalog.study_organisms(site_id, dataset_id)`. A study the site
  publishes no record for runs on none. No served tool schema changes.
- `veupathdb-mcp` is 0.2.0a40. `catalog.organism_parameter` names the marked
  parameter only when its leaves share an organism with the leaves of the site's
  `GenesByTaxon` organism parameter. A marked tree that lists samples under its
  organism branches, such as plasmodb `GenesByMassSpec.ms_assay`, names none, so a
  host reads no organism scope from its sample terms. A site whose `GenesByTaxon`
  is not read keeps the mark. `tests/unit/catalog/fixtures` holds the plasmodb
  `GenesByMassSpec` and the plasmodb and vectorbase `GenesByTaxon` definitions. No
  served tool schema changes.
- `veupathdb-mcp` is 0.2.0a39. A curated search and a curated study run on their
  dataset's assay: `SearchCatalog.dataset_assay(search_name)` is the assay every card
  that names the search records (none when they differ), and
  `SearchCatalog.study_assay(dataset_id)` is the card's with that id. A host reads them as
  `veupathdb_mcp.catalog.dataset_assay(site_id, search_name)` and
  `veupathdb_mcp.catalog.study_assay(site_id, dataset_id)`. The assay is the record's
  `newcategory`, else its `type`, from the `AllDatasets` report the build already posts
  ([the decision](decisions/a-curated-search-runs-on-its-datasets-assay.md)).
  `tests/_support/recorded_catalog.py` builds a catalog from a recorded report for both
  dataset tests. No served tool schema changes and no snapshot format change.

- `veupathdb-mcp` is 0.2.0a38. A search that exactly one dataset names runs on that
  dataset's organisms: `ExperimentCard.organisms` lists the organisms of a card apart,
  `SearchCatalog.dataset_organisms(search_name)` returns those of the one card whose
  `searches` names the search, and none when no card or several cards name it, and
  `veupathdb_mcp.catalog.dataset_organisms(site_id, search_name)` is the host's read
  beside `organism_parameter`, which outranks it. The source is the `AllDatasets` report
  the catalog build already posts (`organism_prefix` and the `References` table); every
  organism it lists for a dataset with a gene search is a term of the site's organism
  vocabulary on five sites ([the decision](decisions/a-dataset-search-runs-on-its-datasets-organism.md)).
  `tests/unit/catalog/fixtures/cryptodb_all_datasets.json` is the recorded cryptodb
  report. No served tool schema changes.

- A step or a report whose values hold no term list reads no search definition
  (`veupathdb-py` 0.1.0a22), so the controls step of a measure, a confirm and an
  enrichment reads none: `MEASURE_REQUESTS` is 9, `confirm_requests(leaves)` is
  `4 * leaves + 5` and `ENRICHMENT_REQUESTS` is 33, each the recorded run's count.
  Pyright reads `separation/` clean: `SeparationOperator` names the three combine
  operators an assembled boolean takes.

- `veupathdb-mcp` is 0.2.0a37 and takes `veupathdb-py` 0.1.0a22. A lookup ranks the
  request's own words first: `VocabNarrowing.request` is the concept in the request's
  words, `read_options(options, terms, *, request_terms)` reads them as a term is, and
  the kept entries they match rank first, phrase before word, while the phrasings alone
  decide which entries are kept. `VocabLookup.request_terms` and
  `VocabLookup.request_matches` name what ranked, `ParameterInfo.allowed_values_from_request`
  counts the shown entries that carry those words, and a cut list's note says how many of
  them it holds ([the lookup decision](decisions/a-vocabulary-lookup-reads-the-phrasings-of-a-term.md)).
  The two vocabulary caps, `_MAX_VOCAB_ENTRIES` (50) and `_MAX_NARROWED_ENTRIES` (300),
  live in `param_formatting` beside `_capped_vocab_fields`, which picks the cap from the
  read's lookup. `gene_sample_attributes` names the attributes each gene record type
  declares: `transcript` reads `gene_product`, `gene_name` and `organism`, and `gene`
  reads `product`, `name` and `organism`. WDK refuses an attribute a record type does
  not declare; every recorded catalog under `data/catalogs/` declares these, and
  `tests/unit/test_tool_payloads.py` reads them there. No served tool schema changes.

## 2026-10-03

- `veupathdb-mcp` is 0.2.0a36 and takes `veupathdb-py` 0.1.0a20, whose EDA client
  runs the dimensionality-reduction compute and reads the service's plot statistics.
  The served tools are unchanged.

## 2026-09-30

- `veupathdb-mcp` is 0.2.0a35. An entry a vocabulary query unions in as a prompt
  is not a value: `vocab_rendering.is_prompt_entry` reads its label, which asks for
  a choice ("Choose chromosome", "Choose a Module", "Choose a public or private Gene
  List User Dataset") or names none ("--None--"). WDK marks such a row no other way:
  ApiCommonModel's `ChromosomeOrderNum` and `ChromosomeForNgsSnps` union
  `'Choose chromosome'` in at order -1 (`sharedParams.xml`), the WGCNA module query
  unions term `1_choose_module` with the label "Choose a Module", the user-dataset
  queries union term `bla` or `1111` with a "Choose a ..." label (`geneParams.xml`),
  and the continent query unions `--None--` (`popsetParams.xml`); the web client
  compares the chromosome value with the literal (`DynSpansBySourceId.tsx`). The
  recorded plasmodb `GenesByLocation` sheet ships "Choose chromosome" as the first
  term and as `initialDisplayValue`. `ParameterInfo.allowed_values`,
  `vocab_leaves` and a narrowed read leave such an entry out,
  `ParameterInfo.prompt_values` names its term, and `is_placeholder` is true for
  it. Falsified by `tests/unit/catalog/test_a_prompt_entry_is_no_value.py`.

- `veupathdb-mcp` is 0.2.0a34. A query-narrowed vocabulary travels whole up to 300
  entries, and a list cut at its bound carries `ParameterInfo.allowed_values_total` and
  the note "Showing N of M values": a read of the recorded N. fowleri Pfam vocabulary for
  "peptidase" shows all 66 entries, and an unnarrowed read shows 50 of 3,745.
  `VocabNarrowing.query` and the `get_parameter_options` tool take one phrase or several
  phrasings of one concept, and `ParameterInfo.vocab_lookup` (`VocabLookup`,
  `PhrasingMatch`, both on the `veupathdb_mcp.catalog` surface) names each phrasing that
  matched and the entries it matched first. The rule is
  [a vocabulary lookup reads the phrasings of a term](decisions/a-vocabulary-lookup-reads-the-phrasings-of-a-term.md).
  `ParameterInfo.is_placeholder(value)` says whether a value is the radio off value `N/A`
  or a site's "(Example: ...)" prompt and not a term the vocabulary offers; `RADIO_OFF`
  moves to `catalog/param_formatting.py` beside it, and `check_radio_pairs` reads a free-text
  half through it. `format_typed_param` takes one `ParamDependencies` in place of the two
  dependency maps, built by `param_dependencies`, and `phyletic_options_for` no longer
  takes a query. Falsified by `tests/unit/catalog/test_a_narrowed_vocabulary_travels_whole.py`,
  `tests/unit/catalog/test_a_lookup_reads_several_phrasings.py` and
  `tests/unit/catalog/test_a_placeholder_is_no_value.py`.

## 2026-09-29

- `veupathdb-mcp` is 0.2.0a33. `EdaBackedSearch.is_compute_backed` is read from the
  search's definition: a search that reads the spec runs a compute when it opens an EDA
  notebook (`properties.edaNotebookType`) or is the generic `GenesByEdaVizWithCompute`
  export. On the twelve sites' transcript listings, every search that declares a
  notebook runs a compute except the inert `GenesByWGCNAModule`: 584 differential-expression
  and 5 antibody-array searches on `GenesByEdaVizWithCompute`, and the 12
  `GenesByDESeqUserDataset`, which runs its own query and reads the volcano cut in its spec.
  No subset search (`GenesByEdaSubset`, `GenesByEdaSubsetGeneric`,
  `GenesByPhenotypeUserDataset`) declares one. The spec does not decide the kind: a subset
  export keeps the analysis's computations. Falsified by
  `tests/unit/catalog/test_a_search_that_opens_a_notebook_runs_a_compute.py`.

- `veupathdb-mcp` is 0.2.0a32. `ParameterInfo.is_read_only` carries the `isReadOnly`
  WDK sets on a parameter only the site sets, read through the client's
  `WDKBaseParameter.is_read_only`: on plasmodb `GenesByText`, `document_type` is hidden
  and read-only with no vocabulary, while `channel` on the Gomez-Diaz percentile search is
  hidden, not read-only, with the vocabulary `Channel 1`, `Channel 2`. Hidden means not
  shown, not fixed, so `build_sheet` lists a hidden parameter that has a vocabulary, with
  `SheetEntry.hidden` set, and leaves out a hidden parameter without one.
  `format_search_overview` still lists visible parameters only. Falsified by
  `tests/unit/catalog/test_a_hidden_choice_is_on_the_sheet.py`.

## 2026-09-27

- `veupathdb-mcp` is 0.2.0a31. It pins `veupathdb-py` v0.1.0a19, whose parameter model
  reads `is_organism` from the `properties.organismProperties` WDK sets on the search's
  organism parameter (WDK-PARAM-013 in the client bundle). `ParameterInfo.organism_param`,
  `SheetEntry.organism_param` and `ParamOverviewEntry.organism_param` carry that mark, so
  `get_parameter_options`, `get_search_overview` and the sheet name the organism parameter
  whatever WDK calls it: `organismSinglePick` on plasmodb `GenesByNgsSnps`,
  `organism_select_none` on vectorbase `GenesByGeneModelChars`, `organism` on
  `GenesByMolecularWeight`. `veupathdb_mcp.catalog.organism_parameter(site_id, record_type,
  search_name)` answers the marked parameter's name from the cached search details, or None
  for a search with no mark. The mark means an organism-organized vocabulary: plasmodb marks
  `ms_assay` (`GenesByMassSpec`) and `ptm_assay` (`GenesByPTM`), whose leaves are
  experiments. `format_normalized_param_info` leaves `param_formatting`: no module read it,
  and its input carries no mark. Falsified by
  `tests/unit/catalog/test_the_organism_parameter_is_the_one_wdk_marks.py`.

## 2026-09-24

- A search that takes an input step is listed whatever its question set.
  `list_transforms(site, "transcript")` answered only `TranscriptsFromGenes` and
  `GenesBySpanLogic` on fungidb, plasmodb, toxodb, vectorbase and the portal, because it
  skipped every search filed under `InternalQuestions`; it now answers
  `TranscriptsFromGenes`, `GenesByOrthologs`, `GenesByPathwaysTransform`,
  `GenesByCompoundsTransform`, `GenesByWeightFilter` and `GenesBySpanLogic` on the four
  component sites, and `TranscriptsFromGenes`, `GenesByOrthologs`, `GenesByWeightFilter` and
  `GenesBySpanLogic` on the portal. `list_searches`, `browse_search_categories` and the
  candidates of `search_for_searches` offer the same input-step searches, and the semantic
  injection no longer names the boolean question or a chooser search. The predicates live
  in `catalog/search_offer.py`, which takes `is_chooser_search` from `catalog/scoring.py`.
  See [An input-step search is listed whatever its question set](decisions/an-input-step-search-is-listed-whatever-its-question-set.md).

- A dataset whose publication row has no PMID keeps the site's datasets. On vectorbase
  and the portal, the Publications row of `DS_af57b0e081` is a DOI linkout with `pmid`
  null, so `DatasetReport` refused the whole report and both catalogs held 0 datasets.
  `DatasetPublication.pmid` is optional; the rebuilt catalogs hold 613 (vectorbase) and 2592
  (portal). Falsified by
  `tests/unit/catalog/test_experiment_cards.py::test_a_publication_without_a_pmid_keeps_its_dataset`.

- A sample of a built step sends no view filter. On a transcript step the
  `representativeTranscriptOnly` filter makes WDK rank the whole answer before it returns a
  row: a union with the whole P. falciparum 3D7 genome (5720 genes, 5791 transcripts) took
  longer than the client's 30 s attempt three times over, so `step_sample_records(limit=8)`
  failed after 188 s, while the same page without the filter answered in 0.6 s.
  `step_sample_records` and the served `get_step_sample_records` now share
  `veupathdb_mcp/wdk/step_preview.py::step_sample_answer`: it reads `4 * limit` rows from
  offset 0 without the filter, keeps the first row of each gene (the first part of the
  primary key, `gene_source_id` on a transcript) in the order read, and reads one more page
  only when the first holds fewer distinct genes than both `limit` and the step's gene count.
  The same sample answers in 0.5 s. The pagers keep the filter: a page past offset 0 needs
  one row per gene to reach the last genes. `StepResultsService` and `step_results_service`
  leave `veupathdb_mcp.wdk` with the module that held them, and so do the names only they
  read: `AttributesResponse`, `RecordAttribute`, `RecordDetailResponse`,
  `build_attribute_list`, `extract_detail_attributes` and `merge_analysis_params`. The
  enrichment service builds its own analysis request. Falsified by
  `tests/unit/wdk/test_step_preview.py::TestASampleIsOneRowPerGene` and the live lane's
  `tests/live/test_the_sample_of_a_genome_union_is_quick.py`.

- `veupathdb-mcp` is 0.2.0a25. It pins `veupathdb-py` v0.1.0a16, whose VDI and EDA
  user-scoped calls never fall back to the service token. A control test names every
  control id it was given. A positive set is `PositiveControls` (`recoveredIds`, `missedIds`), a negative set is
  `NegativeControls` (`admittedIds`, `excludedIds`); `ControlSetData`,
  `IntersectionSummary` and `summarize_intersection` leave `veupathdb_mcp.controls`.
  `controlsCount`, `intersectionCount`, `recall` and `falsePositiveRate` are computed
  from the two lists, so a consumer reads a count from its list and never from a field
  stated apart from it. `ControlOutcome` replaces `positiveIntersectionIds`,
  `positiveMissingIds` and `negativeIntersectionIds` with `positiveRecoveredIds`,
  `positiveMissedIds`, `negativeAdmittedIds` and `negativeExcludedIds`; its six counts and
  rates keep their wire names and are computed from those lists. No list is cut: the
  step runner pages through every record of the step, and the search runner reads every
  id of the intersection whatever the size of the control set. See
  [A control test files every id it was given](decisions/a-control-test-files-every-id-it-was-given.md).

## 2026-09-23

- `veupathdb-mcp` is 0.2.0a24: it pins `veupathdb-py` v0.1.0a15, whose analysis document
  holds every compute plugin the site offers (`EdaComputeDescriptor` and
  `EdaVisualizationDescriptor` unions, `differential_expression_computations`,
  `analysis_descriptor_patch`). No code of this distribution changes; the pin moves so a
  host that takes the client release resolves one URL for it.

- `veupathdb-mcp` is 0.2.0a23. `search_for_searches` returns only the searches that a term, a
  keyword or the semantic index matched, so a query that matches nothing returns an empty list.
  `relevance` is relative to the best hit of the same answer, so the top hit reads 1.0 however
  weak it is. `SearchMatch.semantic_similarity` is the cosine of the query against the
  search's indexed text, `None` where the index did not score that search, and serializes as
  `semanticSimilarity` in `to_dict()`. `veupathdb_mcp.catalog.search_similarity(site_id, query,
  search_name)` returns the cosine for one named search, from
  `SemanticSearchIndex.similarity`, which embeds the query once and reads only that entry.

- `veupathdb-mcp` is 0.2.0a22: it pins `veupathdb-py` v0.1.0a14, whose identity read makes one
  attempt under a ten-second deadline and raises on an outage.

- `veupathdb-mcp` is 0.2.0a21: it pins `veupathdb-py` v0.1.0a13, whose step reports take no user
  id and send `viewFilters` beside `reportConfig`, the only place WDK reads them.
- A report that enumerates the records of a transcript step reads one row per gene. The standard
  report of a transcript step has one row per transcript while its count is genes (toxodb 6475
  rows for 6414 genes, plasmodb 3139 for 3073), so a pager that walks `offset` up to the count
  repeats genes and never reaches the last rows. `veupathdb_mcp.wdk.step_report_filters` owns
  the `representativeTranscriptOnly` view filter and sends it on a transcript step only; the
  `gene` record type has no such filter. The pagers that send it: `fetch_gene_ids_from_step`
  and `run_step_control_tests` (the record type WDK reports for the step), and the identifier
  read of a control intersection (the record type the catalog names for the target search).
  The sample read, `step_sample_records` and `step_sample_answer` in `step_preview.py`, which
  the served `get_step_sample_records` also calls, sends no filter (2026-09-24 entry). Count
  reads send nothing: `records_returned()` already prefers the gene count. `veupathdb_mcp.wdk`
  publishes `view_filters_for` and `step_view_filters`, so a host pager applies the same rule.
- `_extract_step_search_context` takes a step's record type from its `recordClassName`, which WDK
  sends as the url segment, so a `gene` step is no longer reported as `transcript`.

## 2026-09-22

- `veupathdb-mcp` is 0.2.0a19: it pins `veupathdb-py` v0.1.0a11, whose search-config update
  carries the step's own input-step values, so a transform's own parameter can be changed.
- `veupathdb-mcp` is 0.2.0a20: it pins `veupathdb-py` v0.1.0a12, one step read per search-config
  update.

## 2026-09-16

- `veupathdb-mcp` is 0.2.0a18. A step the site will not run reports words, not the bundle.
  `veupathdb_mcp.wdk.describe_step_refusal` reads the validation bundle WDK renders inside its
  own prose, follows the answer parameter into the bundle of each input step it names, and
  reports the parameter and the value the site refuses. The three bundle fields
  (`keyedErrors`, `validationLevel`, `validationStatus`) are required, so a JSON object of
  another shape is not read as a bundle and the caller keeps its own text; a bundle whose leaf
  message the reader does not know reports one short sentence instead of the blob. The reader
  names no user, no step id and no JSON, and the caller keeps logging the whole refusal.
  Measured on the refusal a saved two-step strategy got: two nested bundles and four
  identifiers became "This strategy cannot run. The second input of the step you ran sets
  'profileset_generic' to 'P. falciparum Su Strand Specific RNA Seq data - - Sense', which the
  site no longer offers. Open that step and choose a value the site offers now." Enrichment is
  the first caller.

- `veupathdb-mcp` is 0.2.0a17. A gene set taken from a single-step strategy carries that
  search's typed parameters. `_extract_step_search_context` reads the step's own search
  document and decodes its wire values through the seam the strategy snapshot already used,
  which is now `veupathdb_mcp.wdk.param_decoding`: one way to get a search's parameter kinds,
  two callers. Parameters are None when the search document cannot be read and an empty
  mapping when the step sets none of the parameters the search declares, so a caller tells the
  two apart. A step whose document is unreadable still reports its genes and its search name.
  Measured against the recorded `search_genes_by_molecular_weight` document: a step wired with
  `min_molecular_weight=50000`, `max_molecular_weight=50100` and `organism=["Plasmodium
  falciparum 3D7"]` reported no parameters and now reports those three as typed values.

- `veupathdb-mcp` is 0.2.0a17. A count reports no number only when the service answered about
  the one search it asked for. `count_search_answer` reads the refusal's own code, and for a WDK
  refusal its HTTP status: any 4xx is such an answer and leaves that count unknown, while a site
  the deployment does not serve, a caller with no registered token, another service, and any 5xx
  reach the caller, because a null from those says "no records here" where nothing answered at
  all. `compute_plan_step_counts` still reports None for a step whose own count cannot be read.
  Measured both ways: a count that absorbed every refusal answered "this step has no readable
  count" for a site that does not exist, and a host that had refused such a request served 200
  with nulls; and the anonymous report endpoint answers 401 with a request for an API key on
  some searches, so a 401 is the endpoint describing itself and not the caller's standing.

- `veupathdb-mcp` is 0.2.0a16. `count_search_answer` is published from
  `veupathdb_mcp.wdk`: one search counted through the anonymous report endpoint with
  `numRecords: 0`, which creates no step, no strategy and needs no user session. It is the
  count `compute_plan_step_counts` already made for a leaf-only plan, now named and reachable
  by a host, so a host that counts one binding does not carry its own copy. `timeout_seconds`
  bounds one read and reports no count when it expires; the default waits as long as the
  client does, which is what the plan counts pass. An answer that publishes no total now
  reports no count instead of raising, so one unreadable leaf no longer ends a whole plan
  count.

## 2026-09-15

- `veupathdb-mcp` is 0.2.0a15. A search backend that answers 200 with a body its format does
  not hold is one refused attempt, not a dead search: the metasearch and the keyed engine
  both record the attempt and the next engine is asked. A literature API that answers a body
  that is not JSON names itself and is asked once, in place of a raw decode error after three
  attempts.

- `veupathdb-mcp` is 0.2.0a14. `RESEARCH_MCP_SEARXNG_URL` names a SearXNG instance the web
  tool asks first, before a keyed engine and the scraped ones; see
  [A metasearch the deployment runs answers first](decisions/a-metasearch-the-deployment-runs-answers-first.md).
  Startpage joins the scraped engines.

- `veupathdb-mcp` is 0.2.0a13. A web engine that answers and finds nothing has answered:
  a query no engine finds a page for returns an empty result with guidance, and the
  tool raises only when every engine was blocked. Measured: three empty searches in one
  turn were three served errors, and a host that retries a tool three times ended the
  turn with no reply.

- `veupathdb-mcp` is 0.2.0a12. A `10.3410/` DOI (H1 Connect, once Faculty Opinions) is a
  recommendation of a paper and ranks as no article; a query with no letter or digit is
  refused as no query by both search tools.

- `veupathdb-mcp` is 0.2.0a11. An abstract that is the venue name or the title describes
  nothing, so encyclopedia and dictionary entries no longer lead a literature answer.

- `veupathdb-mcp` is 0.2.0a10. With `RESEARCH_MCP_BRAVE_SEARCH_API_KEY` set, the web tool
  asks the Brave Search API before any scraped engine and the served answer carries what
  the call cost (`costUsd`); see
  [A keyed engine answers first and prices the call](decisions/a-keyed-engine-answers-first-and-prices-the-call.md).

- `veupathdb-mcp` is 0.2.0a9. A literature record with an identifier and no abstract that
  describes it ranks below one that has both, so a one-page venue item whose title repeats
  the query no longer leads; see
  [A listing page never outranks a paper](decisions/a-listing-page-never-outranks-a-paper.md).
  When Europe PMC and PubMed both return nothing while other sources answer, the guidance
  says so and asks for a shorter query.

- `veupathdb-mcp` is 0.2.0a8. Literature relevance ranks a paper above a page: a listing
  page, a search page and a DOI prefix that registers no journal article rank below every
  article, and the score decides inside a band. Both search tools now report what they
  searched: one row per literature source with its count and its error, and, for the web,
  the engine that answered and every engine that refused.

## 2026-09-11

- The client pin is `v0.1.0a10`, the release that publishes the signing-key reset, so
  a host that pins both distributions resolves one client URL. `veupathdb-mcp` is 0.2.0a7.

- This bundle exists from this version on. Before it, the rules that bind these two
  servers to a host - which of their functions a host calls in process, which settings
  sources it installs, which alembic chain it runs, and who owns the embedder drift
  gate - were recorded in another repository or in none. The backlog it opens with is
  the set of couplings and downward re-derivations that a host other than the first one
  would hit.

- Eight capabilities that had no tool row have one, so the served inventory is 25 tools
  rather than 17: parameter binding, parameter validation, parameter specs, semantic
  catalog search, plan step counts, control tests on a step, a materialized gene-set
  step, and a step's gene ids. Each carries the contract of the published call it
  wraps, and [what the wire serves](decisions/what-the-wire-serves-and-what-a-host-imports.md)
  states the property that decides the rest. A step's gene ids answer bounded: a step
  that holds more genes than one call carries is refused by name, and the download url
  reads the whole set.

- A materialized gene-set step is remembered per account, not per site and membership,
  so no caller is handed a step id that names a step in somebody else's WDK account. The
  account is the request's own WDK token, because
  [that is what decides where the step lands](decisions/a-frozen-step-is-keyed-by-the-account-it-lands-in.md).
  A call that carries no token is refused rather than cached as anybody.

- The WDK server proves admission in this repository's CI, beside the research server
  and at one conformance pin. A service secret is issued by the deployment that serves,
  so neither lane needs a VEuPathDB account, a site or a database.

- A step read asks for gene attributes only when the caller names a gene record type.
  `gene_sample_attributes` takes `record_type: str`, and no record type stands in for
  another. A host that passed nothing passes its own default at the call site.

- Each setting answers to one name, and that name states no application. The two
  `PATHFINDER_MCP_` alias choices are gone from `McpSettings`, and the index settings
  name the index: `api_debug` is `embedding_sql_echo`, so a host's own SQL echo drives
  the host's engine alone. No checkout produced either old name, so the only variable a
  deployment adds is `EMBEDDING_SQL_ECHO`, in its own compose file and its own
  environment sample, and only when it wants the index to echo.

- The root package re-exports the three leaf modules both servers share. The WDK
  credential path, its settings and its published metadata declare their own surfaces,
  read by module name, because
  [importing any module runs the package `__init__`](decisions/the-root-package-holds-what-both-servers-share.md).

- The conversion from a saved WDK strategy to a strategy AST is
  `veupathdb_mcp.wdk.strategy_snapshot`, published as `build_snapshot_from_wdk` and
  `canonicalize_synced_parameters`. Both ends of it are library shapes, so the
  distribution that owns both shapes owns the conversion.

- One codec states the wire form of a WDK parameter value, and it is the client's.
  `WDK_VOCAB_PARAM_TYPES`, `encode_vocab_value` and `encode_vocab_params` are gone from
  `veupathdb_mcp.wdk`; `encode_param_value` puts one value on the wire for the kind its
  parameter declares. A single pick is now the bare term where this server wrapped it in
  a one-element array, and WDK reads both as the same value. The defaults an analysis
  form offers are carried back as WDK stated them, because a stable value is already a
  wire value. A supplied number takes the canonical form of its kind, so `1.0` reaches
  WDK as `1`. A range or a filter value handed to an analysis request as a wire string is
  refused rather than passed through. No served tool's result changes
  shape: the change is in the analysis request this server sends. The client's next
  fixture pass can pin the two forms this rests on: record
  `GET .../steps/{id}/analyses/{analysisName}` for `go-enrichment` and `word-enrichment`
  on one site, which states the declared kind of `organism` and
  `goAssociationsOntologies`, and one `POST .../steps/{id}/analyses` body carrying the
  bare organism term.

- Every `veupathdb` import in `src/` and in `tests/` names a package surface rather than
  a file inside one, at the client's `v0.1.0a9`. The nine shapes the suite builds are
  published, so fifteen imports in the suite name `veupathdb.domain.parameters` or
  `veupathdb.wdk` and none of them names a module. The client publishes no clear of the
  JWKS signing-key cache, and this suite needs none: `reset_site_router` drops the
  router and every per-site client built from it, and `tests/conftest.py` calls it.

- The two visible phyletic species lists are declared once, on
  `veupathdb.domain.parameters`. `PHYLETIC_LIST_PARAMS` is gone from
  `catalog/param_formatting.py` and from this distribution's surface, and its three call
  sites in `catalog/param_formatting.py` and `catalog/param_phyletic.py` read the
  client's constant. `catalog.is_phyletic_sheet` reads the three names off the client's
  `PhyleticBinding` instead of a second pattern constant, which is one declaration
  fewer. The consuming application moves `PHYLETIC_LIST_PARAMS` out of its
  `veupathdb_mcp.catalog` import in `ai/tools/standalone/frame_spec.py` and reads it
  from `veupathdb.domain.parameters`.

- The step tree fold, its refusal and the record type match are the client's.
  `wdk/step_tree.py` and `wdk/record_types.py` are deleted, `build_wdk_step_tree`,
  `MissingWDKStepIdError` and `resolve_record_type` leave this distribution's surface,
  and `wdk/plan_counts.py`, `catalog/record_type_resolution.py`,
  `catalog/param_resolution.py` and `catalog/param_phyletic.py` read the three names
  from `veupathdb.wdk`. The consuming application reads
  `MissingWDKStepIdError` and `build_wdk_step_tree` from `veupathdb.wdk` in
  `services/strategies/sync.py`; it imports neither name from here.

- What a host does to take this release, beyond the pin: read the four credential,
  settings and metadata names from the modules that publish them rather than from the
  root package; delete its own copy of the WDK strategy conversion and import
  `veupathdb_mcp.wdk`; pass its own record type where it passed nothing to
  `gene_sample_attributes`; read `PHYLETIC_LIST_PARAMS` from
  `veupathdb.domain.parameters` and `build_wdk_step_tree` and `MissingWDKStepIdError`
  from `veupathdb.wdk`; and take the client at `v0.1.0a9`, whose surfaces this release
  resolves against. Nothing else in this release moves a published name a host reads:
  the three codec names that left were read by no host.
