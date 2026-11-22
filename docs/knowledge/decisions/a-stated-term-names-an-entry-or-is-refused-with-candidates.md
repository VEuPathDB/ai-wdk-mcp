---
type: Decision
title: A stated term names an entry or is refused with candidates
description: A stated pick, and a gene lookup's stated organism, bind only to the entry they spell after folding (case, spacing, a numeric equivalent); every other term is refused in one VocabularyEntryError that carries the ranked candidates, an organism guessed from a query never narrows a lookup, and no model chooses an entry; the offline A/B that rejected a Decisions choice, with and without a fit predicate.
tags: [catalog, vocabulary, parameters, decisions-api]
status: stable
---

# The choice

The client's stated reader (`read_stated_values`, which `read_declared` in
`src/veupathdb_mcp/catalog/param_dag.py` calls) names each stated pick through
`entries_or_refusal` (`veupathdb-py: src/veupathdb/domain/parameters/vocab_lookup.py`),
the same step the canonicalizer runs. A term binds to the entry it names after folding
case and spacing, or to the entry a numeric term equals (`exact_entry`). Every other term
of the parameter is gathered into one `VocabularyEntryError`, one fault per term, each
with the first `SHOWN_CANDIDATES` (5) entries `rank_entries` ranks. A parameter with no
vocabulary keeps its terms. Only vocabulary faults of one parameter are gathered, after
every shape fault of the call; any other refusal raises on its own. `_bound` binds
filters only. `separation/eligibility.py` reads an organism through `exact_entry` alone.

The phyletic species lists and a radio pair's free-text half name their nearest entries
from the same `rank_entries`, by `entry_name` (`display (value)`). No served read asks a
model which entry a phrase means, and a parameter read carries no picked entry.

# The gene lookup's organism

`lookup_gene_records` reads a stated `organism` through `entries_or_refusal` against the
organisms the site declares (`gene_lookup/organisms.py:list_organisms`), before any
search: an organism the site does not list is refused with the ranked candidates, and the
entry it names restricts the searches and the records. An organism the query's own words
imply (`rerank.analyse_query`, scored by `organism.score_organism_match`) is a guess: it
adds an organism-restricted search to the pool and weighs the ranking, never removes a
record, and the result names it as `implied_organism`. The fuzzy suggestions of a stated
organism are gone.

# What was measured

An offline A/B on 458 labelled rows over 25 recorded vocabularies (398 not exact after
folding), labelled twice blind and adjudicated before any arm ran (agreement on the kind
97.2%), split into a dev half and a held-out half of 229 rows (197 not exact). Arms:
refuse with the candidates; a Decisions Choice over up to 254 ranked candidates plus
`none_fits` (`gpt-6-luna`); the same Choice capped by a fit predicate. A row is right
when the arm settles the gold entry, or refuses with a gold entry in the first five
candidates or a gold answer of ambiguous or none. A settled wrong entry is confidently
wrong, and an arm with one is not adopted.

- Dev: the Choice alone has a confidently wrong row at every floor from 0.30 to 0.95
  ("proteolysis enzyme" settled to GO:0006508 proteolysis at 0.97). Choice and fit reach
  0 at floor 0.80 (211 of 229).
- Held-out: refuse is right on 197 of 229 (86.0%, Wilson 80.9-89.9%) with 0 confidently
  wrong. Choice and fit at 0.80 is right on 208 (90.8%) with 1 confidently wrong:
  "Duffy binding like domain" settled to IPR008602 at choice 1.00 and fit 0.94, where
  the label is ambiguous between IPR008602 and IPR004258.
- 40 repeated rows gave the same answers. The live pass cost $0.153 (1.53 M input
  tokens); a Choice and fit cost $0.0003 and 1.7 s per row.

With 0 confidently wrong on 197 unclear held-out phrases, the upper 95% bound on the
refuse arm's confident-error rate is 1.52%.

# What was rejected

- **A Decisions Choice with a fit predicate.** About 5 points more accurate, but it
  binds an entry the researcher did not name, with no question asked, on 1 of 197
  held-out rows. A wrong bound term changes a strategy's result silently; a refusal
  costs one more turn.
- **The Choice alone.** No floor removes its confidently wrong rows on dev.
- **The read's pick (`VocabPick`) and its floor setting.** They existed only for the
  rejected arm.

Falsified by `tests/unit/catalog/test_a_stated_phrase_is_read_by_the_resolver.py`,
`tests/unit/catalog/test_a_value_is_read_under_its_parents.py` and
`tests/unit/gene_lookup/test_an_organism_is_stated_or_only_ranks.py`.
