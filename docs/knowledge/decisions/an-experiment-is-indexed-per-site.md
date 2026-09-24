---
type: Decision
title: An experiment is indexed per site
description: Each site's WDK dataset records are cards in an index of their own, `experiments:{site_id}`, with the cards in `experiment_cards`; two new functions rank and read another site's cards, and the own-site search ranking reads none of them.
tags: [catalog, index, experiments, sites]
status: stable
---

# The choice

A catalog build reads the site's `AllDatasets` report and turns each dataset record into
an `ExperimentCard`: the site, the dataset id, the name, the organism, the assay, the
attribution, the summary cut at 600 characters, the PMIDs, the gene searches the dataset
feeds on its own site, and the record URL. The cards are written to the
`experiment_cards` table and embedded in one index per site, `experiments:{site_id}`,
beside the site's search index and under the same sync policy.

Two functions serve them, and both are tools: `rank_experiments_elsewhere(site_id,
query)` ranks every component site except the caller's and the portal, keeps the best
card of each site, drops a card under the search ranking's semantic floor, and returns
the best sites first; `read_experiment(site_id, dataset_id)` returns one card.
Two more read the stored cards in process and are not tools: `sites_holding_organism`
names the component sites with a dataset of an organism, and `sites_publishing(dataset_ids)`
names, in one read, the component sites whose cards hold each dataset id.
`search_for_searches` is not changed: it reads `catalog:{site_id}` and nothing else.
`tests/integration/embeddings/test_the_own_site_lane_is_unchanged.py` proves that its
answer is the same before and after other sites' experiments are indexed.

The cards live in Postgres, not in the catalog snapshot alone, because a catalog can be
evicted under the memory budget, and another site's card must render without its
catalog. The snapshot carries the cards too (`datasets`), at `SNAPSHOT_FORMAT_VERSION`
2, so a format-1 file is refused and rebuilt.

# What was rejected

**Merging every site into one index.** The own-site ranking would change with every
other site's catalog, which breaks the rule that a site's answer is its own. The portal
repeats every component site's searches, so each would rank twice. Search names repeat
across sites, so an entry id would need the site anyway. And a merged ranking hands a
caller another site's search as if it could be bound.

**Indexing other sites' searches instead of their datasets.** A search on another site
is the one thing a caller cannot bind: its step lives in another WDK. The dataset record
carries what informs a criterion here: the organism, the assay, the condition, the
attribution and the publications.

**Composing the two lanes inside `search_for_searches`.** Every host would receive a
changed own-site answer. Where the other sites' entries go in an answer is the host's
presentation, so this distribution serves two functions and the host composes them.

**Keeping `dataset_summaries` and `dataset_contacts` beside the cards.** No reader
consumed either map; the catalog build was their only writer. The cards replace them,
and the report asks only for the attributes and tables a card reads.
