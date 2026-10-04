---
type: Decision
title: A vocabulary lookup reads the phrasings of a term
description: A query narrows a vocabulary by the term as a phrase and as its words in any order, by each uncommon word only when neither matches, and by several terms at once; the kept entries that carry the request's own words rank first; a narrowed list travels whole up to 300 entries and names the total it was cut from.
tags: [catalog, vocabulary, lookup]
status: stable
---

# The choice

`read_options` in `src/veupathdb_mcp/catalog/vocab_lookup.py` is the one rule a query
narrows a vocabulary by, for a list, a tree and the phyletic clade labels. A label and a
term are compared folded: lower case, every run of other characters one space, so
"RNA-binding" and "RNA binding" read alike and "peptidase" still matches
"metallopeptidase". Each term is read as a phrase, then as its words in any order. Each
word alone is read only when neither matched, and only when at most a tenth of the labels
hold it. `VocabNarrowing.query` takes one term or several phrasings of one concept.
Entries rank by reach (phrase, every word, word) and then by vocabulary order, and
`ParameterInfo.vocab_lookup` names each phrasing that matched with the entries it matched
first, so the counts add up to the list.

`VocabNarrowing.request` is the concept in the request's own words, and `read_options`
takes it as `request_terms`. Those words are read as a term is, and the kept entries
they match rank first, phrase before word; the phrasings alone decide which entries are
kept. `VocabLookup.request_matches` names each phrasing of the request's words with the
kept entries it ranked first, `ParameterInfo.allowed_values_from_request` counts the
shown entries that carry them, and a cut list's note says how many of them it holds.

A narrowed list shows up to `_MAX_NARROWED_ENTRIES` (300) entries, a whole vocabulary up to
`_MAX_VOCAB_ENTRIES` (50). A list over its bound sets `ParameterInfo.allowed_values_total`
and says "Showing N of M values".

# What was measured

On the recorded tritrypdb `GenesByInterproDomain` Pfam vocabulary for T. brucei gambiense
DAL972 (2,441 entries), one casefolded substring "rna binding" kept 17 entries. The folded
phrase keeps 24, every word in any order 6 more, including PF14608 "RNA-binding, Nab2-type
zinc finger" and PF12171. PF00076 "RNA recognition motif" and PF00013 "KH domain" hold
neither word, so only a second phrasing reaches them: `["RNA binding", "RNA recognition",
"KH"]` keeps all of them. On the recorded amoebadb vocabulary for N. fowleri ATCC 30894
(3,745 entries), 66 entries hold "peptidase"; the 50-entry cut hid 16 of them, PF13365,
PF02127, PF00930 and PF03416 among them, and said "of many".

On DAL972 again, `["protein", "RNA binding"]` keeps 496 entries, 473 of them under
"protein". Ranked by the phrasings alone, the 300-entry list shows 6 of the 30 entries
that hold "RNA binding". With the request's words "RNA-binding", all 30 rank first.

# What was rejected

- Words alone merged beside the phrase. "rna" alone matches 162 DAL972 labels and
  "binding" 161, so the phrase's 30 entries would sit in front of about 300 others.
- Whole-word matching. It reads "RNA-binding" right but drops "metallopeptidase" and
  "aminopeptidase": 47 of the 66 peptidase entries.
- A semantic index over vocabulary values. It is the way to reach "KH domain" from
  "RNA-binding domain" without a second phrasing, and it is not built here.
- The request's words keeping entries of their own. A word alone of a request matches
  entries that name another concept, and those would rank ahead of every phrasing.

Falsified by `tests/unit/catalog/test_a_lookup_reads_several_phrasings.py`,
`tests/unit/catalog/test_a_lookup_ranks_the_requests_own_words_first.py` and
`tests/unit/catalog/test_a_narrowed_vocabulary_travels_whole.py`.
