---
type: Decision
title: A Decisions choice widens the search candidates and doubts a vocabulary pick
description: search_for_searches always adds the searches an OpenAI Decisions choice over every offered search picks after its own ranking, and a narrowed parameter read carries the entry a choice picks with a confidence that a fit predicate caps; when the service fails, both reads are what they were; and why Jev through OpenRouter, Luna picking in free text, the single Choice confidence and an on-off flag were rejected.
tags: [catalog, search-discovery, vocabulary, decisions-api]
status: stable
---

# The choice

Both reads ask the OpenAI Decisions API (`POST /v1/decisions`, model `gpt-6-luna`)
through `decide` in `src/veupathdb_mcp/catalog/decisions.py`, on every read. The server
does not start without `OPENAI_API_KEY`. `decide` answers None when the service fails, times out
(`DECISIONS_TIMEOUT_SECONDS`) or answers a body that does not parse. A failure logs a
warning. When `decide` answers None, the read returns what it returned before.

- **Search candidates.** `search_for_searches` sends every offered search as choices,
  in even chunks of at most 255, one choice question per chunk, in one request
  (`catalog_choice_request` in `catalog/search_picks.py`). A pick is one of the top 3 of
  a chunk with probability at least `MIN_PICK_PROBABILITY` (0.01). The lexical, site
  and semantic ranking stays as it was. A pick inside the ranking gets
  `decision_probability`. The picks the ranking does not hold come after it, by
  probability, with no `relevance`.
- **Vocabulary entry.** When a query narrows the read, `read_parameter_options` asks
  for one Choice over the kept entries (the first 254, in rank order) plus `none_fits`.
  It then asks one predicate: does the picked entry state the requirement, current and
  neither broader nor narrower? `ParameterInfo.vocab_pick` (`VocabPick`) carries the
  entry (or none), `choice_confidence`, `fit_probability` and `confidence`, the lower of
  the two. `settled` is true when `confidence` is at least
  `DECISIONS_VOCAB_MIN_CONFIDENCE` (0.5). A caller asks the researcher about a pick that
  is not settled. If the fit predicate gets no answer, the read carries no pick.

Neither read holds a rule for a term, a search or a site.

# The searches offered whatever the ranking

`universal_searches(site_id, record_type)` (`catalog/universal.py`) answers the
searches a host appends to every discovery result: the site's text search, when the
site lists it, then every listed search that declares a pair in its `radio-params`
property, in the order the site lists them. It reads the held catalog listing and
sends no request. A vocabulary search that the ranking misses for a term is still
offered, and a site with no declared pair offers text only. A fixed list of search
names was rejected: it cannot follow what each site declares.

# What was measured

The pairs below are the September scorecard sets, scored against the same items' recorded Jev
(`typesafe/jev-1.13`) and Luna (`gpt-5.6-luna`, majority of 3) answers. Spend was $0.21
over 578 requests.

- **Candidates, 150 items over 12 sites and the portal** (12 per site, half
  paraphrase, plus 6 verified hard cases). The label is in the embedding top 30 on 131,
  in the Decisions picks on 138 (mean 4.2 picks), and in the merge of the two on 148.
  Merge against embedding: 17 / 0 discordant, exact McNemar p=1.5e-5. Jev's wide
  Choice: 137 alone, 148 merged; against Decisions 5 / 4. On paraphrased requests the
  embedding holds 56 of 72 and the merge 71. On vectorbase the embedding holds 8 of 13
  and the merge 13. A Choice over the picks is right on 123 (Jev 119, Luna 111 on the
  embedding pool; Decisions against Luna 17 / 5, p=0.017), and it is right 101 of 111
  times at confidence 0.8 or above. One request costs about $0.0013 and 1.2 s (vectorbase
  $0.0028). A pick floor of 0.01 keeps all 138 and drops the zero-weight picks.
- **Vocabulary, 140 items**: all 60 controls whose right answer is none fits, 40
  obsolete GO terms, and 40 ordinary picks. The Choice alone answers `none_fits` on
  5 of 60 (Luna 8, Jev 19) and picks the obsolete term on 19 of 40 (Luna 33, Jev 22).
  With the fit predicate at 0.5, it settles none of the 40 obsolete picks (Luna, at its
  own confidence, leaves 33 unguarded) and leaves 38 of 60 none-fits controls
  unsettled (Luna 14). Paired against Luna: 33 / 0, p=2.3e-10, and 26 / 2, p=3e-6. It
  asks about 8 of its 34 right picks. The unsettled picks it lets through are right 26
  of 28 times. A threshold of 0.8 leaves 50 of 60 unsettled, but asks about 19 of the
  34 right picks.
- On the recorded plasmodb InterPro vocabulary, "protein kinase" keeps 22 entries.
  IPR000719 is not among them, because its label is `serkin_6`. The Choice picks
  IPR011009 at 0.89, and the fit predicate answers 0.31, so the pick is not settled.

# What was rejected

- **Jev (`typesafe/jev-1.13`) through OpenRouter.** Jev found as many candidates (137
  against 138) and was the stronger guard on none-fits controls. It is offered only on
  OpenRouter's alpha decisions endpoint. That would add a vendor and an alpha
  dependency to a served tool. The deployment already holds an OpenAI account.
- **Luna picking in free text, the way the caller picks today.** It picks the most
  ordinary entries (37 of 40). But its self-reported confidence is 0.9 or above on
  nearly every answer. It flags none of its obsolete picks, and it answers none fits on
  only 8 of 60 controls. As a guard it has no signal. Luna on the embedding pool also
  cannot reach a search the pool misses.
- **The Choice confidence alone.** One request is cheaper, but at the threshold that
  asks about as many right picks (0.8, 8 of 34), it leaves 7 obsolete picks settled.
  The fit predicate leaves none.
- **A flag that turns the service on.** Each deployment would have to change its
  environment to get the measured recall and the guard, and a deployment that did not
  would serve the weaker reads with no sign. The key the service needs is the key the
  deployment already holds.
- **The picks merged into the score.** A bonus would reorder the ranking a caller
  already reads. Appending the picks keeps that ranking and still raises recall.

Falsified by `tests/unit/catalog/test_a_catalog_choice_widens_the_search_candidates.py`,
`tests/unit/catalog/test_a_vocabulary_pick_carries_its_confidence.py` and
`tests/unit/catalog/test_the_decisions_client.py`. The recorded exchanges they replay
come from `scripts/record_decisions.py`.
