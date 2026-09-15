---
type: Decision
title: A keyed engine answers first and prices the call
description: With a Brave Search API key the web tool asks Brave before any scraped engine, and the answer carries what the call cost, so the host bills it; scraping stays as the fallback and is free.
tags: [research, web-search, cost]
status: stable
---

# The choice

`WebSearchService` (`src/veupathdb_mcp/research/web/search.py`) asks the Brave Search API
first when `RESEARCH_MCP_BRAVE_SEARCH_API_KEY` is set, and falls through to the scraped
engines in `TEXT_ENGINES` when Brave refuses or returns nothing. The attempt is recorded
in `search_diagnostics` like any engine, under the name `brave-api`.

The answer carries its price: `WebSearchResponse.cost_usd` is
`RESEARCH_MCP_BRAVE_SEARCH_COST_USD` (default 0.005, Brave's $5 per 1,000) when Brave
answered and 0 otherwise, served as `costUsd` on `WebSearchOut`. The host that called the
tool adds it to the user's bill; this server keeps no ledger.

# What was measured

Twenty research questions through a host on the scraped engines alone: Google answered a
captcha on every call, Brave's public page answered 429 on every call, and DuckDuckGo and
Mojeek answered some of the time. One question raised the refusal three times.

# What was rejected

**Scraping only.** The engines that answer change by the hour, and a refusal costs the
host a model round trip each time.

**A price table on the host.** The server knows which engine answered and what it charges;
a host that guesses the price from the engine name is wrong the day the price moves. The
answer is the only place both facts meet.

**Making Brave the only engine.** A key can lapse, a quota can run out; the scraped
engines still answer some of the time and cost nothing.
