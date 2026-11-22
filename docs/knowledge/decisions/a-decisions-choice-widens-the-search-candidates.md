---
type: Decision
title: A Decisions choice widens the search candidates
description: search_for_searches always adds the searches an OpenAI Decisions choice over every offered search picks after its own ranking; when the service fails, the read is what it was; and why Jev through OpenRouter, Luna picking in free text and an on-off flag were rejected. No vocabulary read asks the service.
tags: [catalog, search-discovery, decisions-api]
status: stable
---

# The choice

`search_for_searches` asks the OpenAI Decisions API (`POST /v1/decisions`, model
`gpt-6-luna`) through `decide` in `src/veupathdb_mcp/catalog/decisions.py`, on every read
whose caller passes `about: ResolveContext`. With `about` None it asks nothing
(`search_picks.decision_picks`). The served `search_for_searches` tool passes None: the
server's calls run on the deployment's key, and an outside client could repeat a large
choice on it with every call, so only a host's in-process read, on the transport the host
installs (its turn's keyed provider), asks the choice. The server does not start without
`OPENAI_API_KEY`. `decide` answers None when the service fails, times out
(`DECISIONS_TIMEOUT_SECONDS`) or answers a body that does not parse. A failure logs a
warning. When `decide` answers None, the read returns what it returned before.

- **Search candidates.** `search_for_searches` sends every offered search as choices,
  in even chunks of at most 255, one choice question per chunk, in one request
  (`catalog_choice_request` in `catalog/search_picks.py`). A pick is one of the top 3 of
  a chunk with probability at least `MIN_PICK_PROBABILITY` (0.01). The lexical, site
  and semantic ranking stays as it was. A pick inside the ranking gets
  `decision_probability`. The picks the ranking does not hold come after it, by
  probability, with no `relevance`. `keywords` and `category` travel as one
  `SearchNarrowing`.

The read holds no rule for a term, a search or a site. A vocabulary refusal asks the
service only to order the candidates it shows, never to bind:
[a stated term names an entry or is refused with candidates](a-stated-term-names-an-entry-or-is-refused-with-candidates.md).

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

# What was rejected

- **Jev (`typesafe/jev-1.13`) through OpenRouter.** Jev found as many candidates (137
  against 138). It is offered only on
  OpenRouter's alpha decisions endpoint. That would add a vendor and an alpha
  dependency to a served tool. The deployment already holds an OpenAI account.
- **Luna picking in free text, the way the caller picks today.** Luna on the embedding
  pool cannot reach a search the pool misses, and it is right on 111 picks against the
  Choice's 123.
- **A flag that turns the service on.** Each deployment would have to change its
  environment to get the measured recall, and a deployment that did not
  would serve the weaker reads with no sign. The key the service needs is the key the
  deployment already holds.
- **The picks merged into the score.** A bonus would reorder the ranking a caller
  already reads. Appending the picks keeps that ranking and still raises recall.

Falsified by `tests/unit/catalog/test_a_catalog_choice_widens_the_search_candidates.py`
and `tests/unit/catalog/test_the_decisions_client.py`. The recorded exchanges they replay
come from `scripts/record_decisions.py`.
