---
type: Decision
title: A record that is not a gene is read as a table
description: Columns and tables of every record type except genes are indexed per site in `record-columns:{site_id}`, apart from the search index; `read_search_table` runs one search of such a record type and returns capped rows; `read_site_link` reads what a link into a configured site shows.
tags: [catalog, index, records, links, organism, orthomcl]
status: stable
---

# The choice

Genome facts such as gene counts and BUSCO scores are columns of the organism record
(`genecount`, `busco_genome`, `busco_protein`, `busco_lineage_dataset`), and OrthoMCL keeps
its proteome counts in the `DataSummary` table of its `helper` record. No search names them,
so a search ranking never finds them.

- `veupathdb_mcp.record_fields` reads the columns and tables of an expanded record type.
  The catalog snapshot carries the tables from format 3.
- A catalog build syncs one entry per column and per table into `record-columns:{site_id}`
  (`veupathdb_mcp.embeddings.column_index`). `rank_record_columns` ranks them and drops a hit
  under `COLUMN_FLOOR`.
- `read_search_table(site_id, TableRequest)` runs one search of a record type that is not
  `gene` or `transcript` and returns its rows: one record per row, or one table row per row.
  It asks the site for no more records than the rows it shows (at most 200). Only `contains`
  on records without a table scans more, up to 1000, so a search of millions of sequences or
  groups never sends the site a large report.
  A record type, search, column or table the site lacks is refused with the nearest names
  it has; a WDK refusal is passed on with its message.
- `read_site_link(url)` reads a link that `veupathdb.wdk.parse_site_link` places under a
  configured site: a result of a search that is not a gene search as its table, a gene
  result and a search form by name and values, and a record, strategy, shared strategy or
  other page by what it names. It is not served, because a served tool names one site and
  a link names its own.

# Rejected

- Indexing the columns into the search index. A column then competes with the searches,
  and a question about genes could rank a column over the search that answers it.
- A table read of gene record types. A gene result is a strategy step; a second path to
  the same genes would bypass the step's counts and its revise form.
- A tool per record type, such as an organism table. The catalog says what each site
  carries, so one read serves every record type and every site.

# What falsifies it

`tests/unit/records/`, `tests/integration/records/` and
`tests/integration/embeddings/test_catalog_index.py::test_a_catalog_build_indexes_its_record_columns`,
over QA recordings in `tests/unit/records/fixtures/`.
