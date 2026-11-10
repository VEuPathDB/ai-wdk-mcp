---
type: Decision
title: The agent finds only the searches the ontology offers
description: The listings, the categories and the ranking of search_for_searches offer a search only when the site's Categories ontology names it with target type search and a scope that is absent or names the webservice or the menu; list_transforms and every read by name are not filtered.
tags: [catalog, listings, ontology]
status: stable
---

# The choice

Each site's catalog reads `/ontologies/Categories` from that site. A search is offered when a
node of the tree has `targetType` `search`, names the search's full name in `name`, and has
no `scope` or a `scope` that holds `webservice` or `menu`. The snapshot keeps these names as
`offered_searches` (format 4).

`SearchCatalog.lists` and `SearchCatalog.ranks` add this rule to `is_listed_search` and
`is_ranked_search` (`src/veupathdb_mcp/catalog/search_offer.py`). `list_searches`,
`browse_search_categories`, the lexical and semantic candidates of `search_for_searches`,
the universal searches and the searches `record_columns` names read them. A catalog whose
ontology did not load offers every search, as before.

`list_transforms` is not filtered: a transform is an operation on a step, and
`TranscriptsFromGenes` and `GenesBySpanLogic` are in no ontology. A search the caller names
is still read, validated and run whatever the ontology says.

# What was measured

On 2026-11-10, against the QA sites: PlasmoDB serves 517 searches and the listings offered
425. Of these, 62 are in no ontology node or carry scope `internal` alone: the site metrics,
sitemap and dump searches, the `All*` lists and `GeneQuestions.GenesByEdaSubset`, the test
question whose steps the site's Revise form cannot edit. ToxoDB drops 60, FungiDB 60 and
VectorBase 56. The rule names two searches the listings did not offer, both under
`InternalQuestions`.

Scope `menu` alone tags `OrganismQuestions.GenomeDataTypes` and
`SpanQuestions.IntronJunctionDynamicSearch` on every site, and the dataset choosers under
`InternalGeneDatasetQuestions`, which `hideOperation` already keeps out of the ranking.
`GenomeDataTypes` is the search a genome statistics read lists for the organism record.

# What was rejected

**Scope `webservice` alone.** It drops `GenomeDataTypes`, so a question about genome gene
counts or BUSCO scores finds no search that returns the organism record.

**A list of the two `menu` searches by name.** It offers the same searches today and hides
the next `menu` search a site adds.

**One ontology for every site.** Each site serves its own tree, and the trees differ (2,862
search nodes on PlasmoDB, 2,857 on the others).

**Removing unoffered searches from the catalog.** A step a strategy holds can name one, and
the catalog reads its definition to validate and run it.

Falsified by `tests/unit/catalog/test_the_ontology_names_the_searches_the_agent_finds.py`
and `tests/unit/records/test_a_record_type_lists_its_columns.py`.
