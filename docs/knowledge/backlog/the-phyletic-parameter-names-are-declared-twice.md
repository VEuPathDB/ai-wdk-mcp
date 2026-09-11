---
type: Backlog
title: The phyletic parameter names are declared twice, in two repositories
description: catalog/param_formatting.py names the visible phyletic pair and catalog/param_phyletic.py names profile_pattern, while the client's phyletic module already names all five parameters and the same pattern constant.
tags: [wrong-repo, client, parameters, phyletic]
status: draft
---

# What I did

Read `src/veupathdb_mcp/catalog/param_formatting.py` and
`src/veupathdb_mcp/catalog/param_phyletic.py` against
`veupathdb-py: src/veupathdb/domain/parameters/phyletic.py`.

# What I got

- `catalog/param_formatting.py:31`:
  `PHYLETIC_LIST_PARAMS = frozenset({"included_species", "excluded_species"})`, with the
  docstring "The two visible parameters that state a phyletic criterion".
- `catalog/param_phyletic.py:45`: `_PATTERN_PARAM = "profile_pattern"`.
- The client, `phyletic.py` lines 14 to 27, names all five:
  `PHYLETIC_PARAM_NAMES = frozenset({"profile_pattern", "included_species",
  "excluded_species", "phyletic_indent_map", "phyletic_term_map"})` with "A search is
  phyletic when it carries all five of these parameters", and splits the structural pair
  as `PHYLETIC_MAP_PARAMS = frozenset({"phyletic_term_map", "phyletic_indent_map"})`.
  The same repository declares `_PATTERN_PARAM = "profile_pattern"` at `phyletic.py:273`
  and types the visible pair as fields of `PhyleticBinding` at lines 66 to 68.
- `PHYLETIC_LIST_PARAMS` is a published name of this distribution
  (`tests/unit/published_surface.json`, under `veupathdb_mcp.catalog`).

# Why that's wrong

For the client: which parameters make a search phyletic is one WDK fact about
`GenesByOrthologPattern`, and it is stated in two repositories that release
independently. When a site adds or renames one of the five, the repository that is
updated binds the search and the one that is not either drops a criterion or offers a
parameter WDK no longer has, and the user sees a strategy built from a selection they
did not make. A WDK rule with a checker can only be anchored in one bundle, so whichever
copy is not anchored is the one that rots silently.

# Why it happens

The catalog's formatting and proposal code was written here before the client grew a
phyletic module, and the two names it needs are short enough that retyping them beat
importing them. Nothing fails when the two sets disagree.

# Fix

In the client library first: publish the visible pair as a named constant beside
`PHYLETIC_PARAM_NAMES` and `PHYLETIC_MAP_PARAMS`, and export `_PATTERN_PARAM` under a
public name. That rides a client release.

Then in this repository, in the release that follows `0.2.0a4`: delete
`PHYLETIC_LIST_PARAMS` from `catalog/param_formatting.py` and `_PATTERN_PARAM` from
`catalog/param_phyletic.py`, import both from the client, remove
`PHYLETIC_LIST_PARAMS` from `tests/unit/published_surface.json`, and raise the client
tag in `pyproject.toml`.

The consuming application does not import `PHYLETIC_LIST_PARAMS`, so taking the tag is
a pin change, a `uv lock --upgrade-package veupathdb-mcp` and a `uv sync`.

# What you'd get

One declaration of the five phyletic parameter names, in the repository whose bundle
can pin it to `GenesByOrthologPattern`, and a site that renames one of them breaks one
place instead of disagreeing in two.
