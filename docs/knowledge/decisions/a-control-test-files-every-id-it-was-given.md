---
type: Decision
title: A control test files every id it was given
description: A control test returns each control id on one of two lists and reads every count from those lists, with no sample, no cap and no count-only answer; both runners read only an intersection with the controls, bounded per control id, and delete every step and strategy they write, whatever ends the run.
tags: [controls, payloads, wire]
status: stable
---

# The choice

A control test answers with the controls it was given, each one filed once
(`veupathdb_mcp/controls/control_types.py`): a positive set as `recoveredIds` and
`missedIds` (`PositiveControls`), a negative set as `admittedIds` and `excludedIds`
(`NegativeControls`). `controlsCount`, `intersectionCount`, `recall` and
`falsePositiveRate` are computed fields of those lists, so a count and its list cannot
disagree. The flat `ControlOutcome` carries the same four lists
(`positiveRecoveredIds`, `positiveMissedIds`, `negativeAdmittedIds`,
`negativeExcludedIds`) and computes its six counts and rates from them.

Both runners read only the intersection of the target with the controls. The search runner
builds the target step. The step runner copies the tested step out of its strategy and
intersects the copy, because WDK places a step in one strategy only. The intersection is
always `INTERSECT`, so it lies inside the controls step; `IntersectionConfig` takes no
operator. Its read asks for `TRANSCRIPTS_PER_GENE` (8) records per control id plus one,
and a larger answer is refused, naming the controls search. The step runner reads
`ControlsSearch()` (`GeneByLocusTag` on `transcript`) unless the host names the id search
of its record type. It refuses a step of another record type, or one outside a strategy,
after one `find_step` and before it writes anything.

Both runners and a separation write into the caller's account: the controls dataset, the
target step, the copy or the separation's own steps, the controls step, the combine and an
internal strategy. Every step and the strategy are registered as they are written
(`veupathdb_mcp/controls/account_writes.py`, `run_writes`), and one cleanup deletes them in
the reverse order of creation: the strategy first, then each step that no strategy holds,
one request at a time. A step the deleted strategy held is not deleted on its own, because
WDK refuses to delete a step that a strategy holds (WDK-STEP-007). WDK's strategy delete
removes the steps the strategy holds: measured on QA plasmodb, each of them then answers 404
to a read and to a delete. The cleanup runs when the run ends in any way, a
refusal or a cancellation included. It is shielded from a second cancellation and held by
a strong reference until it ends, and a write still in flight is awaited so that its id is
known. A failed delete is logged and does not replace the error that ended the run. WDK
offers no delete for a dataset, so the dataset stays; it is not listed on the site.

A strategy that WDK made while its answer was lost is not known to the run that wrote it.
Each run therefore names its internal strategy uniquely: the caller's strategy name plus a
run id. Before it writes, each control run and each separation lists the caller's own
strategies and deletes an internal one under its name only when it is older than
`LEFTOVER_AGE` (two days, `controls/control_helpers.py:stale_leftover_ids`, the one rule
every sweep uses). The age is read from `createdTime`, which WDK's strategy listing serves
as a local time with no zone (`YYYY-MM-DDTHH:MM:SS`, with optional fractions). A run lasts
minutes (a served control run is cut at 180 s), and WDK's clock can sit up to 26 hours from
UTC, so two days exceeds both together. A strategy with no readable `createdTime` is kept.
A sweep therefore never deletes the strategy of a run that is still going.

WDK copies a strategy's whole tree (`duplicated-step-tree`) and offers no copy of one
subtree. When the tested step is not the strategy's root, the copies outside its subtree
are deleted at once, one request per step: a leaf of a 20-step strategy costs 20 copies
and 19 deletes. A tested root step costs one copy per step and no delete.

The step runner used to page through every record of the step, 50000 records per read. It
filed the same ids and wrote nothing, but a step of several hundred thousand records cost
one report per page and every record's id, for a test of a few dozen controls. The
intersection answers the same question with at most the controls.

A control is filed by the id the caller gave. A control that WDK returns under another
id, for example an alias, is filed as not returned on both paths.

# What was rejected

**A sample of the ids beside a stated count.** A consumer that names the genes a
strategy missed cannot use twenty of them, and a count stated apart from its list can
drift from it.

**A cap with a `truncated` flag.** The lists partition the controls the call names, so
the answer is never larger than the call's own arguments. A cap would cut an answer no
larger than its question, and every consumer would need a branch for a flag that a real
control set never sets.

**A count and no ids above a fetch limit.** The search runner read no ids for a control
set over 500 and reported only WDK's count of the intersection. Below 500 the count was
WDK's and the missing list compared ids, so a control that WDK returns under another id
was counted as returned and also named as missing. Reading every record of the
intersection costs no more than the controls themselves.

**A sweep by name alone.** It deleted every internal strategy under the run's name, so a run
that started while another run of the same account was in flight deleted that run's
strategy, and the other run's read failed.

**A count of the step, and a refusal above a caller's limit.** The step runner would read
`numRecords: 0`, refuse a step above the limit, and page through a smaller one. That
writes nothing, but a control test on a large result is a real use: a researcher checks
that a broad first step keeps the known genes before narrowing it. A refusal there gives no
answer, where the intersection gives one at the cost of the controls.

# What would prove this wrong

`tests/unit/controls/test_control_ids_are_complete.py`: a set of 25 positives of which
23 are recovered lists all 25 across its two lists, a step is read only through the
intersection, and a search test of 1201 controls files every one.
`tests/unit/controls/test_run_step_control_tests.py`: the tested step's own records are
never read, a step inside a larger strategy is copied alone with its other copies deleted
one at a time, a recorded transcript report files the genes it holds, and an answer past
eight records per control is refused.
`tests/unit/controls/test_a_control_run_leaves_the_account_as_it_found_it.py`: a finished
run, a refused controls step, combine or strategy, and a run cancelled while its strategy
is written each leave no step and no strategy; a second cancellation does not stop the
cleanup; a strategy whose answer was lost is swept once it is stale; a concurrent run's
fresh strategy and a strategy with no time survive a sweep; two runs write two names; a
refused cleanup is logged and the first error is raised.
`tests/unit/controls/test_a_sweep_spares_a_running_strategy.py`: only a stale internal
strategy of the prefix is a leftover, the public cleanup and the search runner keep the
same rule, and `LEFTOVER_AGE` exceeds the served call limit plus 26 hours.
`tests/unit/separation/test_a_separation_leaves_the_account_as_it_found_it.py`: a refused
combine of an assembled tree, and a measurement whose strategy is refused, leave no step.
