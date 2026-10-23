---
type: Decision
title: A search note fills only an empty description
description: A measured note stands in for the description a site does not publish, on every path that reads one, and never replaces a description the site publishes; GroupsBySingleCopy carries the only note, the expression help states the counting, zero and precedence rules the site was measured to follow, and `build_phyletic_expression` writes every expression from a typed pattern, with no path for one question shape.
tags: [catalog, orthomcl, search-guidance, phyletic-expression]
status: stable
---

# The choice

`src/veupathdb_mcp/catalog/search_notes.py` holds a note per site and search.
`described(site_id, search)` puts the note in a search's `description` when the site
sends an empty one, and returns the search unchanged otherwise. Three reads apply it:
`SearchCatalog.get_searches`, which feeds every listing, the ranking candidates,
`find_search` (the searches the semantic index injects) and the text the semantic index
embeds; `read_search_definition`, which feeds `inspect_search` and
`get_search_overview`; and `get_search_parameters`. A note is applied on read and never
stored in the catalog snapshot, so a release that changes a note serves the new text
from an old snapshot.

OrthoMCL's `GroupsBySingleCopy` carries the only note. Its description is empty, its
`queryName` is `ByGenomeCount`, and its three number ranges are those of
`GroupsByGenomeCount`. Measured on build 8.2, the two searches answer the same 8,699
groups at the site defaults, and groups of that answer hold a genome with more than one
protein. The note says what the search returns (groups by the number of genomes with a
protein, in its three ranges), that it does not limit the proteins of one genome and that
an answer from it states that limit, and names the expression that means one protein in
every genome of a named list. It does not compare the search to another one, because a
note that names another search reads as "this search does not answer the question" and
invites dropping the requirement. It also states that the three ranges apply together:
every genome is core or peripheral, so an all-genome range that starts above the sum of
the core and peripheral maxima returns no group. Measured on build 8.2, `all_taxon` from
50 answers no group under the default core and peripheral ranges (2 to 10).

`GroupsByEValue`, `GroupsByOverlap` and `GroupsBySimilarity` get no note, because their
meaning was not measured.

# The expression help

The `phyletic_expression` help in `catalog/param_formatting.py` states what the site
was measured to do on build 8.2, from the OrthoMCLModel source at commit `fcc9dea1`
(`ExpressionParser.java`, `ExpressionParamHandler.java`) and from counts:

- A count ending in T sums genomes that hold a protein, and a bare count sums proteins,
  over the rows of the listed genomes. A group with no row for the list is not in that
  sum, so `<`, `<=` and `>=` never match it: over one list, `<=0T` and `<1T` answer 0
  groups and `=0T` answers 811,525. `=0` and `=0T` are the one absence form, a set
  difference from every group.
- The site writes AND as INTERSECT and OR as UNION with no parentheses around a node, so
  the database reads AND before OR whatever the expression's parentheses say.
  `(A AND B) OR C`, `C OR (A AND B)` and `A AND (B OR C)` each answer 815,746, the count
  of `A AND B` plus the count of `C`. So an OR inside an AND term is multiplied out, and
  absence from at least k of N genomes is written `X AND L<=(N-k)T OR X AND L=0T`, X
  being the other units of that AND term.
- Two sets compare by protein count as bands: one AND term per count k of the right
  side, from 0 to K, the largest count of the right side in any group, read by bisection
  over count reports (`B>=128`, doubling, then halving the last interval). A ladder
  stopped before K misses groups.
- A count's time follows the expression's characters, measured from 6,278 to 645,028
  characters and from 250 to 2,000 OR terms. On QA OrthoMCL with
  `scripts/record_phyletic_site_limits.py`
  (`catalog/data/orthomcl_phyletic_site_limits.json`, read with `importlib.resources`),
  every read answered 200: two-genome ladders of 250, 500, 1,000 and 2,000 terms (6,278
  to 53,779 characters) took 4.5, 5.4, 7.7 and 14.2 s, and 250 terms over units of 8,
  32, 128 and 512 codes (15,028 to 645,028 characters) took 6.5, 11.0, 21.7 and 103.2 s.
  The ladder above 2,000 terms was not sent. Each bisection probe took 0.23 to 0.32 s on
  build 8.2.
- Presence only in a clade L is absence over its complement, `L>=1T AND C=0T`. No
  served read lists the genomes outside a clade, so the builder writes C from the
  taxonomy as the fewest tree codes that cover exactly those genomes. On the recorded
  taxonomy the 855 genomes outside a clade of two are 11 codes.
- The species of a clade are the genome labels' genus and species words (the client's
  `species_of`). A unit written by hand can drop a strain; `each_species_of` writes one
  unit per species from the taxonomy.
- `phyletic_expression` declares `length` 0, and WDK checks a string's length only when
  it is not 0, so the parameter has no length limit. Expressions of 2,842, 4,264 and
  8,644 characters were answered on build 8.2, and up to 645,028 on QA.

# The builder, not recipes

A builder per question shape leaves every other shape to the model and pulls a near
shape toward the reading the builder encodes, and a recipe in the help does the same.
`build_phyletic_expression`
(`catalog/phyletic_pattern.py`, `catalog/phyletic_logic.py`,
`catalog/phyletic_builder.py`) takes the whole grammar instead: counts over sets, a
comparison whose reading the caller states (per genome, totals, averages), and AND, OR
and NOT nested. It reads each condition with absence as 0, multiplies the nesting out
into the OR of AND terms the site reads, and writes each unit in the form the site
counts (`=0` or `=0T` for absence, never an upper bound of zero). The help states the
grammar and names the builder, and no recipe. The five recorded count wires the three
builders sent replay unit for unit against patterns the builder takes, so
`ORTHOMCL_COUNTS` still answers a host's suite
(`tests/unit/catalog/test_the_count_recordings_replay.py`).

# The refusal: the site was not measured to answer it

The expression has no length cap of its own choosing. The builder admits what the
recording shows the site answering and refuses the rest:

- The admission cap is the longest expression the site was measured to answer, read
  from the recording (`SiteCost.longest`, 645,028 characters). A longer expression is
  refused by name before its count, as longer than the longest expression the site
  was measured to answer; it needs recorded rows before it is admitted.
- The predicted time is a second guard. `catalog/site_cost.py` fits the recording's
  answered reads as a fixed cost plus a cost per character, weighted by the inverse
  square of each read's time so every row counts by its relative error: about 3.9 s
  plus 0.138 s per 1,000 characters, every row within 25% (the worst at 22.8%,
  165,028 characters; `tests/unit/catalog/test_the_site_cost_fits_its_recording.py`).
  Each bisection probe adds 0.3 s. A pattern predicted past the 300 s call budget
  (`CALL_SECONDS`, the tool's `_meta`) is refused with the predicted seconds.
- Each refusal names the OR terms and characters. A pattern with no compare is refused
  before any read.
- The bisection reads are bounded before the first one. A distinct compare side takes
  at most 25 count reads (`READS_PER_PROBE`: 10 doubling from 128 to 65,536, then 15
  halving), and the call admits at most the reads the budget leaves after the count of
  the longest admitted expression, `(300 - 92.8) / 0.3`, 690 (`SiteCost.reads_within`).
  A pattern whose
  sides would need more is refused by name before any read; `GroupCountReports`
  refuses the read past that ceiling whatever the prediction said.
- The build's CPU is charged to the same budget. An AND product indexes the added
  clauses by their exact count on one set and tries only the pairs whose bounds on that
  set overlap; every pair it tries is charged before it builds, at 0.72 us a pair
  (`SECONDS_PER_PAIR`), and the build time takes its share of the character cap. A
  product predicted past the budget is refused by name with its pairs
  (`tests/unit/catalog/test_phyletic_product.py`).
- A pattern nests at most 8 levels (`MAX_DEPTH`) and holds at most 128 terms, nested
  terms counted (`MAX_TERMS`); the model refuses a larger one at validation.
- The cap also bounds the build in memory. Each step of the OR-of-AND build, an AND
  product or an OR merge, is admitted after each clause it adds, and its parts are built
  one at a time, so it holds at most the cap and one clause; it is admitted
  on its merged clauses, after contradictions drop and duplicates merge, by the
  characters they write from the pattern's own code covers; a refusal there says the
  pattern reaches at least those counts before its last step. The final rendering is
  admitted on its exact characters before the string exists. No term count is fixed.
- The expansion, the client's parse, check and reading run in a worker thread
  (`asyncio.to_thread`); the client's 0.1.0b23 reads an expression in time linear in its
  units.
- The served result carries the whole expression, the value for `phyletic_expression`.
  Its `reading` is the client's reading while that and the expression are both at most
  2,000 characters (`READING_LIMIT`); past that it is an outline of the pattern (its
  sets, measures, conditions and compare readings) with the OR terms and characters,
  cut to 2,000 characters. A host that keeps a long expression out of a model's context
  does so itself.

# When to measure again

The note and the help name OrthoMCL build 8.2. A new OrthoMCL build leaves them
unmeasured until they are measured again on that build.

# What was rejected

**Hiding the search.** It still answers a question about how many genomes a group
spans, which is what it counts.

**A builder per question shape.** Each covers one reading of one shape, a shape outside
them has no builder, and the model reads a near shape as the one with a builder.

**Leaving the comparison bands to the model.** A ladder written by hand has no stop rule
the model can check from what it sees: a term that answers no group does not mean the
next one answers none, and a ladder copied from another answer stops at that answer's K.
Both miss groups the full ladder returns. The bisection is a bounded number of counts a
tool sends without error.

**Leaving the complement to the model.** No served read lists the genomes outside a
clade, so a model asked for presence only in a clade cannot write C. A tool that walks the
taxonomy writes it exactly and in its shortest form.

**Replacing a description the site publishes.** The site is the authority on its own
searches; a note fills only a gap, and a site that starts to describe the search
retires the note without a release.

Falsified by `tests/unit/catalog/test_search_notes.py`,
`tests/unit/catalog/test_phyletic_expression_builder.py` (every output checked with
`check_expression` and compared group by group with the pattern's meaning on a
synthetic taxonomy, and the budget refusal),
`tests/unit/catalog/test_the_count_recordings_replay.py`,
`tests/unit/test_the_site_limits_recorder_is_bounded.py` and
`tests/unit/catalog/test_param_formatting.py::TestTheExpressionSheetStatesTheGrammarAndNamesTheBuilder`.
