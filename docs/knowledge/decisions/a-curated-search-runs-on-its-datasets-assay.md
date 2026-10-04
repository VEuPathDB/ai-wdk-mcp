---
type: Decision
title: A curated search runs on its dataset's assay
description: The assay of a search that exactly one dataset names, and of a study, is the dataset record's `newcategory`, else its `type`, read from the AllDatasets report the catalog build already posts; and why the search name, the question's `properties`, the coarse `type` alone and the EDA study metadata were rejected.
tags: [catalog, datasets, assay]
status: stable
---

# The choice

A host grounds a data-type requirement ("RNA-Seq") by what a step runs on. A curated
search runs on the dataset that names it in its `References` table, and a curated EDA
study is a dataset record: the study's `datasetId` is the record's `dataset_id`. The
record's `newcategory` attribute, which the site shows as "Category", names the assay:
`RNASeq`, `DNA Microarray Assay`, `scRNA-Seq`, `CHIP Seq`, `Phenotype`, `Immunology`.

`ExperimentCard.assay` already holds `newcategory`, else the record's `type`. The
catalog reads it in two ways, each the assay text: `SearchCatalog.dataset_assay(search_name)`
for the assay every card whose `searches` names the search records, and
`SearchCatalog.study_assay(dataset_id)` for the card with that id. Several cards that
name one search and agree give their assay, because the search runs on one of them
whatever its parameters pick (`GenesByIntronJunctions`: 58 plasmodb datasets, all
`RNASeq`; `GenesByMassSpec`: `Protein expression`); cards that differ
(`GeneByLocusTag`, `GenesByEcNumber`), a card with no assay, a search no card names,
and a study the site holds no record for give none. The organism keeps the one-card
rule, since a search several datasets name picks its organism with a parameter.
`veupathdb_mcp.catalog.dataset_assay` and `veupathdb_mcp.catalog.study_assay` are the
host's reads.

Measured live on plasmodb and toxodb: every gene search whose name holds `RNASeq` or
`Microarray` and that one dataset names has the category the name says (RNASeq, DNA
Microarray Assay, longReadrnaseq), and no such search has another. The category also
marks three profile-similarity searches whose names say nothing of their assay. A
genomic site's EDA study list holds the curated studies of every site; each one the
site's own report holds (73 on plasmodb, 49 on toxodb) carries its category, or the
`isolates` type.

# What was rejected

**The search name.** It is a naming habit of the model templates. A search that names
`microarray` can run on an antibody array, and a profile-similarity search names no assay.

**The question's `properties`.** No property of a curated search names its assay.

**The record's `type` alone.** It is coarse: `transcript_expression` holds RNA-Seq,
microarray, RT-PCR and ChIP datasets alike. It is the assay only when the record has no
category, as on an isolates dataset.

**The EDA study metadata.** A curated study's own document names its entities and
variables, not its assay, and a read of it is one request per study for a fact the
report already holds.
