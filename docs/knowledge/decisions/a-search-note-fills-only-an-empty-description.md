---
type: Decision
title: A search note fills only an empty description
description: A measured note stands in for the description a site does not publish, on every path that reads one, and never replaces a description the site publishes; GroupsBySingleCopy carries the only note, and the expression help states the counting, zero and precedence rules the site was measured to follow.
tags: [catalog, orthomcl, search-guidance, phyletic-expression]
status: stable
---

# The choice

`src/veupathdb_mcp/catalog/search_notes.py` holds a note per site and search.
`described(site_id, search)` puts the note in a search's `description` when the site
sends an empty one, and returns the search unchanged otherwise. Three reads apply it:
`SearchCatalog.get_searches`, which feeds every listing, the ranking candidates,
`find_search` (the searches the semantic index injects) and the text the semantic index
embeds; `read_search_definition`, which feeds `inspect_search` and
`get_search_overview`; and `get_search_parameters`. A note is applied on read and never
stored in the catalog snapshot, so a release that changes a note serves the new text
from an old snapshot.

OrthoMCL's `GroupsBySingleCopy` carries the only note. Its description is empty, its
`queryName` is `ByGenomeCount`, and its three number ranges are those of
`GroupsByGenomeCount`. Measured on build 8.2, the two searches answer the same 8,699
groups at the site defaults, and groups of that answer hold a genome with more than one
protein. The note says so, and names the expression that does mean one protein in every
genome.

`GroupsByEValue`, `GroupsByOverlap` and `GroupsBySimilarity` get no note, because their
meaning was not measured.

# The expression help

The `phyletic_expression` help in `catalog/param_formatting.py` states what the site
was measured to do on build 8.2, from the OrthoMCLModel source at commit `fcc9dea1`
(`ExpressionParser.java`, `ExpressionParamHandler.java`) and from counts:

- A count ending in T sums genomes that hold a protein, and a bare count sums proteins,
  over the rows of the listed genomes. A group with no row for the list is not in that
  sum, so `<`, `<=` and `>=` never match it: over one list, `<=0T` and `<1T` answer 0
  groups and `=0T` answers 811,525. `=0` and `=0T` are the one absence form, a set
  difference from every group.
- The site writes AND as INTERSECT and OR as UNION with no parentheses around a node, so
  the database reads AND before OR whatever the expression's parentheses say.
  `(A AND B) OR C`, `C OR (A AND B)` and `A AND (B OR C)` each answer 815,746, the count
  of `A AND B` plus the count of `C`. So an OR inside an AND term is multiplied out, and
  absence from at least k of N genomes is written `X AND L<=(N-k)T OR X AND L=0T`, X
  being the other units of that AND term.
- Two single genomes compare by protein count as a ladder of AND terms, one per count of
  the smaller side up to K, where K is the smallest count at which `B>=K+1` answers no
  group; K is read from the site by bisection. A group with equal counts in the two
  genomes is not selected.
- `phyletic_expression` declares `length` 0, and WDK checks a string's length only when
  it is not 0, so the parameter has no length limit. Expressions of 2,842 and 4,264
  characters were answered.

# What the help needs from the client

The help tells a model to write an OR of AND terms without parentheses. The parameter
check reads each stated expression with the client's `PhyleticExpression.parse`, and
`veupathdb-py` 0.1.0b17 refuses AND and OR side by side without parentheses. The help
therefore ships only in the same release as the repin to the client release that
accepts an OR of AND terms without parentheses, and that release's test runs the help's
example through the client's parser and its evaluation of an expression on one group.

# When to measure again

The note and the help name OrthoMCL build 8.2. A new OrthoMCL build leaves them
unmeasured until they are measured again on that build.

# What was rejected

**Hiding the search.** It still answers a question about how many genomes a group
spans, which is what it counts.

**Replacing a description the site publishes.** The site is the authority on its own
searches; a note fills only a gap, and a site that starts to describe the search
retires the note without a release.

Falsified by `tests/unit/catalog/test_search_notes.py` and
`tests/unit/catalog/test_param_formatting.py::TestTheExpressionSheetStatesTheGrammarAndTheRecipes`.
