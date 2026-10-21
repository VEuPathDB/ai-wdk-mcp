---
type: Backlog
title: Single Copy Orthogroups says it cannot name a clade
description: OrthoMCL's GroupsBySingleCopy has no description and only taxon-count ranges, so a request for single-copy groups within one clade binds it with the site's default ranges and returns groups from any taxa.
tags: [orthomcl, catalog, search-guidance]
status: draft
---

# What happens

`GroupsBySingleCopy` ("Single Copy Orthogroups") publishes an empty description
and takes three number ranges: `all_taxon`, `core_taxon`, `peripheral_taxon`. It
has no taxon or clade parameter. A request for single-copy groups within one clade
binds this search with the site defaults (all taxa 4 to 20, core 2 to 10,
peripheral 2 to 10) and returns single-copy groups from any taxa.

# Change

Give the search catalog guidance for `GroupsBySingleCopy`: it counts taxa and
cannot restrict to a species or a clade; a copy-number question within named taxa
is a `GroupsByPhyleticPattern` expression, built with codes from
`lookup_phyletic_codes`.

# Done when

The guidance reaches `get_search_overview` and the catalog ranking for
`GroupsBySingleCopy`, and a test asserts it is present.
