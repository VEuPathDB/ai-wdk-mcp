---
type: Decision
title: The catalog shares a search definition across logins
description: The site catalog keeps one copy of each search definition for every login, because no gene search lists a user's own data today, and a step write reads its definitions through the site client, which keeps each one for fifteen minutes under its login; a per-request catalog was rejected for the load it puts on the sites.
tags: [catalog, search-definitions, wdk-load, users]
status: stable
---

# The choice

`SearchCatalog.get_search_details` (`veupathdb_mcp/catalog/discovery.py`) keeps one
copy of each search definition per site and answers every login from it. The parameter
forms, parameter resolution and validation read it.

WDK builds a definition for the user who asks, and a vocabulary query may take that
user's id (veupathdb-py WDK-VOCAB-008). EbrcModelCommon has one such vocabulary, the
Target Gene List of a step analysis form. No gene search uses one, so every login reads
the same definition from the catalog.

A step write does not read the catalog's copy. It reads through the site client, which
keeps each definition for fifteen minutes under that login only (veupathdb-py,
`decisions/a-turn-reads-once-and-a-definition-is-kept-for-a-time.md`), so a separation
run reads each definition once in any fifteen minutes; a run that lasts longer reads it
again, and its charges do not count that read.

Each site release is checked for a gene search whose vocabulary takes `user_id`. One
such search would make the catalog's copy show the first login's data to every other
login.

# What was rejected

**A per-request catalog.** Keeping the catalog's definitions only for one request reads
WDK again on every parameter form, every resolution and every validation, which adds
load on the sites for a search no site serves yet.

**A copy per login token.** Each login would hold its own copy of definitions that are
the same for almost every user. The memory grows with logins times searches, and a
bound on it lowers the hits as logins grow.
