---
type: Decision
title: A listing page never outranks a paper
description: Literature relevance sorts by what a record is before it sorts by how well its title matches, because the fuzzy title score rewards the short stubs a researcher never wants first.
tags: [research, literature, ranking]
status: stable
---

# The choice

`sort_results` in `src/veupathdb_mcp/research/literature/processing.py` orders relevance
results by a band first and the fuzzy score second. The bands, from `EnrichedPaper.rank_band`:
a record with a DOI or PMID and an abstract that describes it; a record with a DOI or PMID
and no such abstract; any other article; and everything that is not an article (a bioRxiv
or medRxiv keyword, search or collection page, a landing page with no identifier, a Protein
Data Bank DOI). Inside a band the score decides, and a lower band is still returned when it
is all the search found.

"Describes it" is one rule, `describing_abstract` in `research/text.py`: the abstract or
snippet, stripped, at least forty characters, and not the venue name or the title itself.
The scorer already ignored anything shorter; the bands read the same rule. The second
clause was measured in: encyclopedia and dictionary entries titled "Mitosome" carry their
venue name as the abstract, sixty characters long, and led every answer to a Giardia
question until the top slots held nothing a reader could use.

# What was measured

One query, eight results across four sources, the same before and after the bands were
added to `test_ranking.py`: a Science-Business eXchange one-page item whose title repeats
the query outscored every paper on the fuzzy title score (66 against 52 for the best
paper). Both registries type it as a journal article. Its record carries no abstract from
any source, one page, no references in OpenAlex and no citations. The bands put it below
the three papers whose records describe them, and above the papers that carry no abstract
in any source either.

# What was rejected

**Raising the abstract weight.** The stubs have no abstract to score, and the scorer zeroes
any abstract shorter than the floor, so no weight moves them. Real papers with a rich
abstract and a specific title would gain a little; the stubs would lose nothing.

**A venue blocklist.** Naming Science-Business eXchange, the Protein Data Bank and the
next venue that turns up needs upkeep no test can drive, and the same publisher prefix
(`10.1038/`) registers Nature papers beside the stubs. The two prefixes that are kept are
the ones Crossref shows register almost nothing else: `10.2210/` (structures) and
`10.3410/` (H1 Connect, once Faculty Opinions: 247,177 datasets against 506 articles,
read from the Crossref prefix facet on 2026-09-15). Four of 34 citations in one run were
recommendations of a paper under that prefix rather than the paper.

**Citation and reference counts.** OpenAlex, Semantic Scholar and Crossref all carry
them, and a record cited by nothing that cites nothing is a stub. But the reference
lists of papers from the 1980s and 1990s were never deposited, so the same rule demotes
them, and it needs a threshold on the age. The abstract is in the record already.
