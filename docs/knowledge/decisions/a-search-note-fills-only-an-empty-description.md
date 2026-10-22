---
type: Decision
title: A search note fills only an empty description
description: A measured note stands in for the description a site does not publish, on every path that reads one, and never replaces a description the site publishes; GroupsBySingleCopy carries the only note, the expression help states the counting, zero, precedence and complement rules the site was measured to follow, `build_protein_count_comparison` builds the two-genome protein ladder and `build_clade_only_expression` the presence-only-in-a-clade expression.
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
protein. The note says what the search returns (groups by the number of genomes with a
protein, in its three ranges), that it does not limit the proteins of one genome and that
an answer from it states that limit, and names the expression that means one protein in
every genome of a named list. It does not compare the search to another one, because a
note that names another search reads as "this search does not answer the question" and
invites dropping the requirement. It also states that the three ranges apply together:
every genome is core or peripheral, so an all-genome range that starts above the sum of
the core and peripheral maxima returns no group. Measured on build 8.2, `all_taxon` from
50 answers no group under the default core and peripheral ranges (2 to 10).

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
  group. A group with equal counts in the two genomes is not selected. The served tool
  `build_protein_count_comparison` (`catalog/protein_comparison.py`) reads K by bisection
  over count reports and counts the ladder, and the help names it as the way to build
  one. The bisection probes `B>=128` and doubles up to `B>=1024`, then halves the last
  interval, so one call sends at most 15 count reports (13 probes and two ladders), one
  after another under the client's one-search-per-site line. The reverse ladder stops at
  K - 1, because a term past it asks `B>=K+1`, which answers nothing.
- A ladder count takes time in proportion to its length. Measured on QA build 8.2, a
  call with both ladders took 10.2 s at K = 111 (ladders of 2,690 and 2,664 characters,
  4.0 and 4.3 s), 20.2 s at K = 212 (5,316 and 5,290 characters, 9.1 and 8.7 s) and
  25.6 s at K = 340 (8,644 and 8,618 characters, 10.5 and 11.6 s), each bisection probe
  0.23 to 0.32 s. The two directions of one genome pair agree: each ladder total is the
  same whichever genome the bisection reads. The slowest ladder ran at 42 ms per term,
  so a call at the largest accepted K, 1,023, needs about 2 x 1,024 x 0.042 s for its
  ladders and 13 x 0.3 s for its probes, about 90 s. The call budget is 120 s: 4.7 times
  the slowest measured call, and above that estimate. A B with 1024 or more proteins in
  one group is refused by name, because its ladders would pass the budget; a refusal
  states why, where a timeout states nothing. The longest ladder measured,
  8,644 characters, is the longest expression the site was measured to answer.
- Presence only in a clade L is absence over its complement: `L>=1T AND C=0T`, with C
  every genome outside L. No served read lists the genomes outside a clade
  (`lookup_phyletic_codes` gives at most 20 matches and no parent), so the help names
  `build_clade_only_expression` (`catalog/clade_only.py`), which writes C from the
  taxonomy and counts it with one report. C is the fewest tree codes that cover exactly
  the genomes outside L: a clade code wherever a whole clade lies outside, a genome code
  for the rest, and no code for a clade with no genome. On the recorded taxonomy the 855
  genomes outside a clade of two are 11 codes, and the 839 outside a genus of 18 genomes
  with no clade code are 53. With `within`, a clade M that holds L, C is every genome
  outside M; an M that does not hold L is refused, and the refusal names
  `L>=1T AND M=0T`, the form for absence from M.
- `phyletic_expression` declares `length` 0, and WDK checks a string's length only when
  it is not 0, so the parameter has no length limit. Expressions of 2,842, 4,264 and
  8,644 characters were answered.

# What the help needs from the client

The help tells a model to write an OR of AND terms without parentheses. The parameter
check reads each stated expression with the client's `PhyleticExpression.parse` and
judges it with `check_expression`. `veupathdb-py` 0.1.0b17 refuses AND and OR side by
side without parentheses, so the help ships with the pin to 0.1.0b18, which accepts an
OR of AND terms and refuses an upper bound of zero (`<=0` or `<1`), because such a unit
matches no group. Each recipe and the example pass the served check and select, with
the client's evaluation of an expression on one group, the groups their words describe:
each instance has groups it must select and groups it must reject, and every one-edit
change of an instance (an operator, a count up or down by one, T added or removed, a unit
or an OR term dropped) that selects other groups fails on one of them. Two recipe forms
reach a bound of zero at an edge, so the help names the edge: absence from at least k is
for k below N, and absence from all N genomes is `X AND L=0T`; band c=0 over one genome
in L1 is `L1=0T AND Y` alone. In band c=0, Y is `L2>=1`, because at least r times 0
proteins states nothing and the check refuses `L2>=0`.

# When to measure again

The note and the help name OrthoMCL build 8.2. A new OrthoMCL build leaves them
unmeasured until they are measured again on that build.

# What was rejected

**Hiding the search.** It still answers a question about how many genomes a group
spans, which is what it counts.

**Leaving the two-genome ladder to the model.** A ladder written by hand has no stop rule
the model can check from what it sees: a term that answers no group does not mean the
next one answers none, and a ladder copied from another answer stops at that answer's K.
Both miss groups the full ladder returns. The bisection is a bounded number of counts a
tool sends without error, and the expression it returns is the one the help describes.

**Leaving the complement to the model.** No served read lists the genomes outside a
clade, so a model asked for presence only in a clade cannot write C. A tool that walks the
taxonomy writes it exactly and in its shortest form.

**Replacing a description the site publishes.** The site is the authority on its own
searches; a note fills only a gap, and a site that starts to describe the search
retires the note without a release.

Falsified by `tests/unit/catalog/test_search_notes.py`,
`tests/unit/catalog/test_protein_count_comparison.py`,
`tests/unit/catalog/test_clade_only_expression.py` (with the recorded counts in
`tests/unit/catalog/fixtures/orthomcl_clade_only_counts.json`),
`tests/unit/catalog/test_param_formatting.py::TestTheExpressionSheetStatesTheGrammarAndTheRecipes`
and `tests/unit/catalog/test_the_help_recipes_parse.py`.
