---
type: Decision
title: An input-step search is listed whatever its question set
description: The catalog listings offer every search that takes an input step, and leave out the boolean question by its shape, because WDK files the orthology transform under InternalQuestions.
tags: [catalog, listings, transforms]
status: stable
---

# The choice

`src/veupathdb_mcp/catalog/search_offer.py` decides which searches a listing offers.
`list_transforms` keeps every search with a non-empty `allowedPrimaryInputRecordClassNames`
except the boolean question. `list_searches` keeps the same input-step searches and, of the
searches that take no input, those outside `InternalQuestions`.
`browse_search_categories`, the lexical candidates of `search_for_searches` and the
searches its semantic index injects also leave out the chooser searches (`hideOperation`).

The boolean question is the search that takes a secondary input step and declares three
parameters: the two operands and `bq_operator`, which is what `BooleanQuery.setRecordClass`
builds (`veupathdb-py: docs/knowledge/wdk/rules/strategies-and-steps.md`, WDK-STEP-001 and
WDK-STEP-006). `GenesBySpanLogic` also takes two input steps, and declares twenty
parameters, so it stays listed.

# What was measured

On 2026-09-24, `list_transforms(site, "transcript")` answered `TranscriptsFromGenes` and
`GenesBySpanLogic` on fungidb, plasmodb, toxodb, vectorbase and the portal. WDK files
`GenesByOrthologs`, `GenesByPathwaysTransform`, `GenesByCompoundsTransform` and
`GenesByWeightFilter` under `InternalQuestions` on the four component sites, and
`GenesByOrthologs` and `GenesByWeightFilter` on the portal, so the listing skipped them. The
lexical candidates of `search_for_searches` skipped the same searches. The semantic index
holds every search, so its injection could name the boolean question.

# What was rejected

**The question set as the filter.** `InternalQuestions` holds the orthology transform
beside the boolean question and the basket searches, so the set name does not separate a
search a researcher binds from one a strategy builds for itself.

**The name prefix `boolean_question`.** WDK's own client matches it
([`Operations.tsx`](https://github.com/VEuPathDB/web-monorepo/blob/main/packages/libs/wdk-client/src/Utils/Operations.tsx)),
and a naming convention is what WDK-STEP-001 warns against. The shape is what WDK constructs.

**The boolean shape as "two answer parameters" alone.** `GenesBySpanLogic` has two, and it
is a step a researcher binds.

**Removing unlisted searches from the semantic index.** `search_similarity` scores any
search a step binds, so the index keeps every search and the injection filters.

Falsified by `tests/unit/catalog/test_search_listings.py`,
`tests/unit/catalog/test_semantic_matching.py::test_an_injected_hit_is_a_search_the_listings_offer`
and the live lane's `tests/live/test_the_orthology_transform_is_listed.py`.
