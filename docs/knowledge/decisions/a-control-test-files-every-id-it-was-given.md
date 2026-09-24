---
type: Decision
title: A control test files every id it was given
description: A control test returns each control id on one of two lists and reads every count from those lists, with no sample, no cap and no count-only answer, because the lists are never larger than the call's own arguments.
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

Both runners read every id they file. The step runner pages through every record of the
step (one page of 50000 records per read). The search runner reads every record of the
intersection step, which lies inside the controls step.

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

# What would prove this wrong

`tests/unit/controls/test_control_ids_are_complete.py`: a set of 25 positives of which
23 are recovered lists all 25 across its two lists, a step past one page is read to its
last record, and a search test of 1201 controls files every one.
