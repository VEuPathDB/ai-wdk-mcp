---
type: Decision
title: A radio pair offers a term as two readings
description: For a search whose two halves one query ORs, a term is offered as the entries whose label names it, with the free-text half off, and as the free-text wildcard, with the vocabulary half at its own off entry; the two are never one binding, each is counted as its own search, and a lookup over an accession vocabulary states how many entries a name cannot reach.
tags: [catalog, vocabulary, radio-params]
status: stable
---

# The choice

`radio_readings(pairs, params, term)` in `src/veupathdb_mcp/catalog/radio_readings.py`
reads each pair a search declares in `radio-params` and answers `RadioReadings`:

- `label`: a `LabelReading` with the entries whose label names the term (phrase and
  every-word reach of `read_options`), the vocabulary half set to them and the
  free-text half set to `N/A`. A single-pick half binds only when one entry matches;
  `label_values` lists the entries either way.
- `description`: a `DescriptionReading` with the free-text half set to `*term*` and the
  vocabulary half set to `N/A`. It is offered only when the vocabulary half's own
  vocabulary holds the entry `N/A`.
- `accession`: `AccessionNames` (`entries`, `one_token`, `nameless`) when every label is
  the value followed by a name.

`read_radio_readings(site_id, search_name, term, *, record_type, context_values)` reads
the parameters under the parents the caller binds and calls `radio_readings`. Each
reading's `params` goes to `count_search_answer` beside the caller's other values.

`check_radio_pairs` accepts a free-text value beside a vocabulary half bound to `N/A`
when that vocabulary holds `N/A`. A free-text value beside any other vocabulary value is
an issue, as before.

`read_parameter_options` adds one sentence to `allowed_values_note` for an accession
vocabulary whose names include one token or none: how many there are, and that an entry
no label names can still be on the site.

# What was measured

On qa.plasmodb.org, `GenesByInterproDomain` under organism Plasmodium falciparum 3D7 and
`domain_database` INTERPRO:

- The vocabulary has 4,718 terms. The last is `N/A`, from the `UNION SELECT 'N/A'` row of
  `GeneVQ.DomainAccession`. `domain_typeahead: ["N/A"]` with
  `domain_accession: "*protein kinase*"` validates `isValid: true`.
- 1,166 of the 4,717 named entries carry a name of one token, and 321 of them carry `-`.
  IPR000719 is labelled `IPR000719 : serkin_6`, so "protein kinase" reaches 22 entries by
  label and not IPR000719.
- Anonymous report counts, transcripts: `["IPR000719"]` with the free text off 98;
  `["N/A"]` with `*protein kinase domain*` 99, holding every IPR000719 gene but one;
  `["N/A"]` with `*protein kinase*` 127, holding every IPR000719 gene.

# What was rejected

- One binding that fills both halves. The query ORs them, so the count is the union and
  no field says so.
- A zero-gene entry to switch the vocabulary half off. `N/A` is the off entry the model
  declares; any other entry is a value that can gain genes.
- A description reading on a vocabulary without `N/A`. Its vocabulary half cannot be
  switched off, so the reading is a union.

Falsified by `tests/unit/catalog/test_a_radio_pair_offers_two_readings.py` and
`tests/unit/catalog/test_radio_pairs.py`.
