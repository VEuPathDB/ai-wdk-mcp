---
type: Decision
title: A dataset search runs on its dataset's organism
description: A search that exactly one dataset names in its References table has the organisms that dataset's `organism_prefix` lists, read from the AllDatasets report the catalog build already posts; a search several datasets name has none, and why the question's `properties.organisms`, a per-search `DatasetsByQuestionName` read, the `Version` table and a union over datasets were rejected.
tags: [catalog, organisms, datasets]
status: stable
---

# The choice

WDK marks a search's organism parameter with `properties.organismProperties`. A
search generated for one dataset, such as an RNA-Seq percentile or fold-change search,
publishes no such parameter: its organism is the organism of the data it runs on. WDK
publishes that link on the dataset record. The `References` table of
`DatasetRecordClasses.DatasetRecordClass` names each question a dataset feeds, and the
record's `organism_prefix` names its organisms, one per `<br>`.

The catalog build already posts the `AllDatasets` report with both, and keeps each record
as an `ExperimentCard`. `ExperimentCard.organisms` lists the organisms apart, and
`SearchCatalog.dataset_organisms(search_name)` returns the organisms of the one card
whose `searches` names the search. A search that no card names, or that two or more name,
has none. `veupathdb_mcp.catalog.dataset_organisms(site_id, search_name)` is the read a
host makes beside `organism_parameter`; the parameter WDK marks outranks it.

Measured on cryptodb, amoebadb, tritrypdb, vectorbase and plasmodb: every organism that
a dataset with a gene search lists is a term of the site's organism vocabulary, so a host
compares it with a marked parameter's value as it is. Of the gene searches that exactly
one dataset names, 1,348 mark no organism parameter and one marks one. The searches that
several datasets name and that mark none are `GeneByLocusTag`, `GenesByLocation`,
`GenesByNonnuclearLocation`, `GenesByCentromereProximity` and `GenesBySingleCell`.

`tests/unit/catalog/test_a_dataset_search_runs_on_its_datasets_organism.py` reads the
recorded cryptodb report, `tests/unit/catalog/fixtures/cryptodb_all_datasets.json`
(`scripts/record_all_datasets.py cryptodb`), and the plasmodb one for a dataset of
several organisms.

# What was rejected

**The question's own `properties.organisms`.** It is one list per site, the same on
every search of the site and on the dataset record type's own searches. On cryptodb it
names three species, one of them misspelled, whatever the search runs on.

**A `DatasetsByQuestionName` read per search.** It answers from the same `References`
table, so it adds one request per search and no fact the report does not hold.

**The `Version` table's `organism` column.** It agrees with `organism_prefix` on every
dataset that feeds a gene search but one, where it reads `ALL` and the prefix is empty,
and the report would ask for a table the cards do not otherwise read.

**The union of the organisms of every dataset that names the search.** A search that
several datasets name picks one with a parameter or answers every genome, and a
`References` table that leaves out one genome makes the union too narrow. A scope that
is too narrow makes a cross-organism check refuse a combination that has results.

**Reading the organism out of the search name.** The dataset name inside a search name
is a naming habit of the model templates, not a published field.
