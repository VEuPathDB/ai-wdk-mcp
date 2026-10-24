---
type: Decision
title: A compare past one expression is computed from group clouds
description: A compare whose phyletic expression passes the measured caps is computed from each set's per-group protein counts, read with the sequence search's group word cloud, at most 24 requests one at a time, and answered as a snapshot of the same groups the expression would select; a compare that would also select groups neither set holds is refused; the caps stay where they are.
tags: [orthomcl, phyletic, wdk, budget]
status: stable
---

# The choice

`build_phyletic_expression` answers a `PhyleticPattern`. When the whole pattern is a
`compare` and its expression would pass `MAX_EXPRESSION_TERMS`,
`CHARACTERS_WITHIN_READ_TIMEOUT` or `MAX_EXPRESSION_WORK`, or the site's measured count
time, `answer_phyletic_pattern` (`wdk/phyletic_counts.py`) computes it instead and
answers `ComputedComparisonResult` with `route: "computed"`. Under the caps the answer
is the expression, `route: "expression"`, as before. A whole-pattern compare whose
smallest expression (every largest count read as 0) already passes a cap goes to the
count route with no probe read; otherwise the probe reads it spent before the expression
was found too large are reported as `probeRequests`, beside `computeRequests`. A compare
inside `all_of`, `any_of` or `none_of` is refused past the caps; the refusal says so
when the pattern with that compare at its smallest counts fits, and is the original
too-large refusal otherwise.

**The counts.** `group_link-wordCloud` on `sequence/ByTaxonomy`, with
`taxon_type_ahead` as a JSON array of genome codes, answers one word per group with the
set's proteins in that group (`wdk/group_clouds.py`). Every word must be a core group id
or a residual group id (`catalog/phyletic_compare.py::GROUP_ID`), the counts must sum to
the search's record count read with `numRecords: 0`, and the reporter's single
"Too many words" word past 10,000 groups is refused. On QA OrthoMCL the read reproduced
the expression ladder of tgon against pfal exactly (3,896 groups) and each set's word
count equals its `>=1T` group count, residual groups included.

**The slices.** Every set, a lone genome included, is counted first with one
`<cover>>=1T` report. A set past 10,000 groups is halved in tree order until each half
fits, each half read on its own, and the halves summed per group. A lone genome past
10,000 groups cannot be split, so it is refused in the plan, before any cloud, with
`GenomePastCloudCapError`, which names the genome and its group count. The plan, counts
included, must fit `MAX_COMPARISON_REQUESTS` (24) before the first cloud is read; a
larger plan is refused with the slices as the narrower sets to try. `per_genome` counts
and reads each genome on its own, 3 requests a genome, so it is refused past 24 requests
as needing a background task. The count route shares the expression route's 300 s call
budget from the start of the call: each request goes out only while time remains, carries
the time left as its budget, and a call that runs out is refused with
`ComparisonOutOfTimeError`.

**The comparison selects what the expression selects.** Each set reduces to a span per
group: a mean or a total for `averages` and `totals`, the least and the most genome for
`per_genome`, an absent genome counted 0. The compare runs over every group either set
holds, so a group one set holds is in `groupIds` exactly when the expression would select
it. `bothHeld`, `leftOnly` and `rightOnly` split those same groups by the set that holds
them, and `ties` counts the groups whose two sides are equal. A group neither set holds is
in no cloud. A compare that holds at 0 against 0 (`at_least`, `at_most`, `exactly`) would
select every such group, so the count route refuses it before any read
(`AbsentGroupsCompareError`); `more_than` and `fewer_than` never select one.

# Rejected

- **Raising the caps.** A 2.6M-character expression froze QA OrthoMCL through the
  recursion of WDK's expression parser. The caps protect the site.
- **Several expressions, one per band of counts, combined by a boolean strategy.** Each
  piece still meets the parser, and a 15-against-61 genome mean writes at least 1,438 OR
  terms; the count route reads the same answer in 6 requests.
- **Each group's `TaxonCounts` table.** One record read per group pages through every
  group of both sets; a cloud reads a whole set in one report.
- **A cloud per genome for every reading.** Requests grow with genomes; a set-level
  cloud is one read per slice and answers `averages` and `totals` exactly.

# What falsifies it

`tests/unit/wdk/test_phyletic_counts.py`: the genus mean (1,884 held by both and 5,480
left only, 371 ties, 17 probe and 6 compute requests); the tgon against pfal computed ids
equal to the ids the written ladder expression selects when `holds_for` evaluates it on
the recorded per-group counts, with the site's side checked through the recorded count,
3,896; the same for a `fewer_than` expression; slices; and each refusal, a lone genome
past the cap and the call budget among them. `tests/unit/catalog/test_phyletic_compare.py`
checks every reading against the synthetic truth the expression builder is tested on,
and `tests/unit/wdk/test_group_clouds.py` the cloud's refusals, over the recordings in
`veupathdb_mcp.testing.ORTHOMCL_GROUP_CLOUDS`.
