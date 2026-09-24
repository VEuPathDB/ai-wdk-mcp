---
type: Decision
title: A separation is measured on the site
description: A run that looks for the strategy separating positive genes from negative ones scores every candidate with a real WDK count, assembles each candidate by the control set its controls beat chance in, reports the assembled tree's own read, charges a request budget from measured request counts, and reads both control sets from one intersection against one uploaded dataset.
tags: [controls, separation, wdk, budget]
status: stable
---

# The choice

`veupathdb_mcp.separation.separate` takes a positive and a negative gene list, a mode
(`exact` or `similar`) and a request budget, and returns a `SeparationResult`.

**Every score is a WDK count.** A candidate is a search bound on the site's own
definition. It runs as a WDK step inside an internal strategy, and the step's count and
the controls it returns are read from WDK (`separation/measure.py`). The run makes no
estimate. A candidate that WDK refuses is skipped with WDK's own words.

**Five sources propose candidates, each with a quota** (`separation/enumerate.py`), in
this order: the leaves the thread already runs, the catalog hits of the literature
queries the caller passes in (three a query), the GO and pathway terms the site finds
enriched in the positives (ten), the product names two or more positives share, bound
into the text search on the product field (five), and every gene search of the catalog
that binds from the organism alone, for the rest of the budget. The organism parameter
is found by its vocabulary, not by its name. An enriched term binds the one vocabulary
entry WDK lists for it: a GO id as itself, a pathway as `(<id>) (<source>)` with the
source its enrichment row names; an entry the sheet does not list is `vocabulary_miss`.
A search is skipped when a gene list cannot intersect it: another record class
(WDK-STEP-008), an answer parameter (WDK-STEP-001), an analysis spec, a dataset
parameter (WDK-PARAM-009), or a required parameter nothing binds. A skip is never a
guess.

**A candidate informs in one direction, or not at all.** The tails draw every control
a candidate returned from the tested controls (`separation/stats.py`,
`MeasuredCandidate.informs`). It is `recovering` when P(X >= recovered), with the
positives as the successes, is under 0.05; `excluding` when the mirror,
P(Y >= admitted) with the negatives as the successes, is under 0.05; and `neither`
otherwise. A candidate that passes both is `recovering`. A candidate of `neither` stays
in `measured` and never enters a tree. On plasmodb, GenesWithAlphafold (80 of 80
positives, 39 of 40 negatives) and GenesByGeneModelChars (80 of 80, 55 of 55) are
`neither`, and GenesWithSignalPeptide at SignalP-6.0 (52 of 80, 2 of 40) is
`recovering`.

**The assembly is greedy, and the tree it builds is read back**
(`separation/assemble.py`). COVER takes the recovering candidate that holds every
positive with the fewest negatives, or unions the recovering candidates that add the
most positives. The tree then removes negatives, the move that removes the most first:
an INTERSECT with a recovering candidate that holds every positive the tree recovers, in
both modes, or, in exact mode only, a MINUS of an excluding candidate that holds none of
the positives the tree recovers, so no move drops a recovered positive. A tie goes to
the INTERSECT, then to the smaller result. The subtracted candidate is the right input
of its MINUS. A tree holds at most six criteria. Set algebra on the control ids only
chooses the moves. The run then builds the tree as one internal strategy and reads its
count and its controls from WDK; that read is the result, and `predictedMatchesRead`
says whether the prediction agreed.

**What separates means.** Exact: every positive and no negative. Similar: every
positive, and a read of the assembled tree that is itself recovering. When the sets do
not separate, the result keeps the closest tree and names each gap in `shortfall`; with
no recovering candidate, the sentence is "No measured criterion tells the positives
from the negatives."

**The budget is an estimate of requests.** `budget` is the requests the caller allows,
and `chargedRequests` what the run charged. Each charge is the HTTP request count its
stage made on plasmodb, recorded in `tests/unit/separation/fixtures/one_run_requests.json`
and replayed by `tests/unit/separation/test_request_charges.py`: an id resolution 4, the
cleanup list 3, the upload 2, a measurement 10, the first read of a search 1, the first
intersection 2 more, the enrichment 34, and a confirm read of `n` leaves `4n + 6`. The
enrichment polls each analysis, so a slow site makes more requests than the charge. A
request budget must hold the confirm reservation of a six-leaf tree.

**One dataset, one intersection.** A run uploads the positives and the negatives
together once, and each candidate is one intersection against that dataset
(`controls.intersect_with_controls`). The search control test uses the same function,
so a test of both sets makes ten client calls with its cleanup list.

# What was rejected

**Model-estimated scores.** A model's guess of how many positives a search holds cannot
be checked and drifts between runs. The model's only inputs are the lists, the mode, the
budget and the literature queries; a query is a hypothesis the counts accept or reject.

**Scoring outside WDK.** A downloaded annotation file, a local product table or the
semantic index's text disagrees with the site the day the site updates, and the strategy
must run on the site. Membership is read from WDK steps only.

**A fixed candidate list.** The searches are a property of each deployment, a list goes
stale, and it cannot hold the thread's searches or a paper's hypothesis.

**Ranking by recall alone.** On plasmodb a search that returns nearly every gene holds
every positive, so a recall-first cover took it and offered the whole genome as a
separation. The direction test removes such a search before the ranking.

**Two intersections per candidate.** A positive intersection and a negative intersection
upload two datasets where one intersection against one dataset reads both sets.

**The unpersisted report per candidate.** A report without a step reads every row of the
result, thousands for a feature search, where the intersection reads at most the
controls.

**One scalar score for both modes.** A score that trades a negative for positives would
call a tree with one admitted negative better than a clean one. Exact mode is
lexicographic: every positive, then no negative, then the smallest result.

**An exhaustive minimal conjunction.** Minimum set cover is NP-hard, and an optimum the
site did not confirm is a prediction. Greedy plus the confirm read reports what the site
returns.

**Counting requests in the HTTP client.** The client exposes no hook, so the run charges
measured constants and the replay test keeps them true.

**Literature search in the run.** Turning a paper into catalog query words needs a model;
the caller reads the papers and passes queries with their references.

# What would prove this wrong

`tests/unit/separation/`: the assembly by direction, the verdicts of the three plasmodb
searches above, a subtraction of an excluding candidate and the refusal of one that
holds a recovered positive, the hypergeometric tail against the exact sum, the
shortfall sentences, the eligibility rules on recorded search bodies, the pathway entry
bound by its source, the request charges replayed from the recorded run, and a budget
that pays for three of ten measurements.
`tests/unit/controls/test_one_intersection_reads_both_sets.py`: a search control test of
three positives and two negatives makes ten client calls and uploads one dataset.
`tests/live/test_one_intersection_files_both_sets.py`: on plasmodb, the one-intersection
filing equals a run of each set alone and a read of the search's whole answer.
