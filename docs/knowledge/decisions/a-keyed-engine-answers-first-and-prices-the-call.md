---
type: Decision
title: A keyed engine answers first and prices the call
description: Reversed. The web tool asked the Brave Search API before the scraped engines and priced each call on the answer; the deployment runs its own SearXNG, so the paid keyed engine, its key, its price and the cost on the answer are gone.
tags: [research, web-search, cost]
status: deprecated
---

# The choice, reversed

`WebSearchService` (`src/veupathdb_mcp/research/web/search.py`) asked the Brave Search API
first when a key was set, and served its per-call price as `costUsd` on `WebSearchOut` for
the host to bill.

The deployment runs its own SearXNG, which answers web searches first at no cost
([the metasearch decision](a-metasearch-the-deployment-runs-answers-first.md)). A paid
keyed engine is not used, so the keyed engine, its key and price settings, and the cost
field on the answer are deleted. No served tool prices its answer now.
`tests/unit/research/test_shaping.py::test_a_served_web_search_carries_no_price` and
`tests/unit/research/test_web_search.py::test_a_web_search_answer_carries_no_price` fail
if a price returns to the answer.

# What was measured

Twenty research questions through a host on the scraped engines alone: Google answered a
captcha on every call, Brave's public page answered 429 on every call, and DuckDuckGo and
Mojeek answered some of the time.

# What replaced it

The metasearch the deployment runs, then the engines `ddgs` scrapes. Both are free.
