---
type: Decision
title: A stated term names an entry or is refused with candidates
description: A stated pick, and a gene lookup's stated organism, bind only to the entry they spell after folding (case, spacing, a numeric equivalent); every other term is refused in one VocabularyEntryError whose shown candidates lead with the entry a Decisions choice picks, which never binds, an organism guessed from a query never narrows a lookup; the offline A/B of four arms that chose refusing over picking.
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
vocabulary keeps its terms. The entry faults of every parameter of the call are gathered
into that one refusal; with a shape fault beside them the call raises one refusal that
names both, each row with its `detail`. `_bound` binds filters only. `separation/eligibility.py` reads an organism through `exact_entry` alone.

The phyletic species lists and a radio pair's free-text half name their nearest entries
from the same `rank_entries`, by `entry_name` (`display (value)`). A parameter read
carries no picked entry.

# The order of the shown candidates

Every async read that can refuse a term orders its refusal through
`ordered_refusal` / `ordered_by_vocabulary` (`catalog/vocab_resolve.py`): the two walks
in `catalog/param_dag.py` (`read_under_parents` and `resolve_params_with_intent`) and the
canonicalizer calls of `validate_parameters` and `validate_search_params` through
`refuse_ordered`, which reads the entry rows of any refusal, and the gene lookup's stated
organism (`lookup_genes_by_text`). Each takes a required keyword
`about: ResolveContext | None`: the site and the researcher's message, or None, which
sends no choice. A served tool passes None: the server's Decisions calls run on the
deployment's key, and an outside client could otherwise spend it on every refusal, so
only a host's in-process read, on the turn's keyed provider, orders a refusal. A
refusal that joins entry rows with other rows (a wrong shape, an unknown name, a wrong
kind, a filter that selects nothing) orders the candidates of every entry row and keeps
each other row in its place. A walk reads every pass before it refuses: a name of no
parameter, a site-set name, a site-set parameter with no value, a value that does not read,
a phyletic list that derives no pattern and a filter that selects nothing are each noted, the
walk skips only the parameters under a refused one, and it raises one refusal at the end. Its
rows are in call order, by the position of their parameter in the call, then in the order
they were found; a row of a parameter the call does not name comes last. Every row holds
`param` and a one-line `detail`.

The refusal's class depends on its rows only, never on `about`: a refusal with no entry row
is raised as it is, one whose every row is an entry row is a `VocabularyEntryError`, and a
mixed one is a `ValidationError` built from its rows (`vocab_resolve.ordered`). Callers read
rows, not classes. One
refusal asks a choice for at most its first `SHOWN_CANDIDATES` (5) terms, all at once
(`ordered_terms`, the one function every path goes through); every later term keeps the
ranking. The phyletic refusal (`PhyleticListError` for a species list term that names no
node) is ordered the same way over the clade labels (`ordered_phyletic_refusal`), each
unknown term asking its own choice under the list's display name.

A radio pair's `nearest` (`check_radio_pairs`) is not ordered. It is not a refusal of a
term the vocabulary was asked to name: the free text is a valid wildcard criterion, and
the issue says that both halves are stated, offering the vocabulary entries as the other
reading beside it. The naming step itself is the client's synchronous stated
reader, so the ordering wraps the readers rather than living in `_bound`.
For each fault it asks one Decisions Choice (`resolve_request`: the site, the parameter's
display name, the words, the message) over the first 254 entries `rank_entries` ranks,
plus `none_fits`. When the choice names an offered entry, that entry leads the five shown
candidates and the ranking follows without it. The choice never binds: the refusal stands
whatever its confidence, and no floor or fit predicate is read. With no answer (no key, a
timeout, a mock deployment, a parse failure), `none_fits` or a choice that names no
offered entry, the fault keeps the ranking. The call runs through `decide`, on whatever
transport the host installs (the turn's keyed provider) and the Decisions timeout.
The separation enumerator passes `about=None` to `resolve_params_with_intent`: it skips a
candidate a refusal names and shows the refusal to no one. The web editor's
context read (`param_resolution`) drops a value it cannot name and refuses nothing.

# The gene lookup's organism

`lookup_gene_records` reads a stated `organism` through `entries_or_refusal` against the
organisms the site declares (`catalog/organisms.py:list_organisms`), before any
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
`none_fits` (`gpt-6-luna`); the same Choice capped by a fit predicate; and, scored
offline from the recorded Choice answers and pre-registered before scoring, refuse with
the Choice's pick leading the shown five (`refuse_plus`). A row is right
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
- Held-out, refuse_plus: right on 219 of 229 (95.6%, Wilson 92.1-97.6%), 22 rows that
  refuse misses and 0 it gets, and 0 confidently wrong because it never settles.
  "citric acid cycle" on the Hagai pathways: the Choice picks `Mitochondrial TCA cycle`
  at 0.92, which the ranking's five do not hold. On dev it is right on 217 of 229 (refuse
  204); a floor on the pick changed nothing from 0.00 to 0.45. The pre-registered rule
  (at least 2 points over refuse) holds at +9.6. One Choice per unclear phrase costs
  about $0.00029 and 0.87 s (median).
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
- **Refuse with the ranking alone.** Never wrong, but 22 held-out refusals did not show
  the entry the researcher meant, where the Choice's pick would have.

Falsified by `tests/unit/catalog/test_a_stated_phrase_is_read_by_the_resolver.py`,
`tests/unit/catalog/test_a_refusal_leads_with_the_decided_entry.py`,
`tests/unit/catalog/test_a_value_is_read_under_its_parents.py` and
`tests/unit/gene_lookup/test_an_organism_is_stated_or_only_ranks.py`.
