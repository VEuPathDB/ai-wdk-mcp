---
type: Decision
title: A metasearch the deployment runs answers first
description: With RESEARCH_MCP_SEARXNG_URL set the web tool asks the deployment's own SearXNG before a keyed engine or a scraped one, because a metasearch that fans out to many engines answered the queries every scraped engine had refused, at no cost and with no key.
tags: [research, web-search, cost]
status: stable
---

# The choice

`WebSearchService` asks, in order: the SearXNG instance `RESEARCH_MCP_SEARXNG_URL` names
(its `/search?format=json` endpoint), the Brave Search API when a key is set, then the
scraped engines in `TEXT_ENGINES`. The first engine that returns a row answers; an engine
that returns none has answered empty; an engine that fails is recorded as refused. Every
attempt is listed in `search_diagnostics`.

# What was measured

Twelve queries that every scraped engine had refused during two study runs were sent to a
SearXNG container run beside the stack (`searxng/searxng`, JSON format enabled, limiter
off). Eleven of twelve returned 7 to 40 results on each of two passes, median 0.4 s.
Nearly every result came through SearXNG's Google CSE engine; its Brave and DuckDuckGo
engines were captcha-suspended under repetition, which is the same fate the scraped path
meets directly. The one miss was a `site:` query no engine indexes.

# What was rejected

**Scraping engines directly and only.** The engines that answer change by the hour, and a
refusal costs the host a model round trip each time; measured, zero of the twelve answered.

**A keyed engine first.** Brave charges per call and needs a card on file; the metasearch
costs nothing per call. The keyed engine stays as the second answer for a deployment that
has one.

**A headless browser.** Slow, heavy in the image, and an arms race against captchas that
needs a paid solver at any scale.

# What this depends on

One instance, one operator, and SearXNG's upstream engines. When the instance is down the
attempt is recorded and the search goes on to the next engine, so the tool degrades to what
it was and never dies on the metasearch alone.
