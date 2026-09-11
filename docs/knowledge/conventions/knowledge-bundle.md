---
type: Convention
title: Maintaining this bundle, and the gate that keeps it honest
description: What belongs in veupathdb-mcp's knowledge bundle, the shape OKF v0.2 requires, how a page in another repository is cited, and why check-knowledge.mjs is a copy.
tags: [conventions, gates, knowledge-bundle]
status: stable
---

# What belongs here

Three kinds of thing, and nothing else:

- **Decisions** - a choice that had a real alternative, where the reasoning is not
  recoverable by reading the code.
- **Backlog items** - work known to be outstanding, with enough context that a fresh
  session picks one up cold.
- **Conventions** - how this repository is worked on, where a tool does not already
  enforce it.

What WDK and EDA themselves do is the client library's bundle, not this one:
`veupathdb-py: docs/knowledge/index.md`. What the assistant runtime does is the
platform's: `assistant-platform: docs/knowledge/index.md`.

# What does not belong here

- Anything `README.md` already states. The served variables, the two processes and the
  two version tables are documented there, and a second copy drifts from the first.
- Anything this repository's own code, tests or type signatures already say.
- Anything the consuming application states about itself. This distribution names no
  such dependency, and a page here that assumes one is wrong for every other host.
- Session narrative.

# Update the bundle in the same change, always

- **Delete the backlog item** when the work is done. Items are removed, never crossed
  out or marked done.
- **Remove its line from `backlog/index.md`** in the same change. The gate fails on a
  dangling link and on a concept no index links to, so a file and its index cannot
  drift apart.
- **Write the decision** if the work settled a question with a real alternative.
- **Add a log entry** saying what left the backlog, including work closed as won't-do.

When every item is finished, `backlog/` holds nothing but `index.md`.

# The rule that stops it rotting

A file here must be falsifiable, and something must falsify it. Every page names the
file, the test or the command that would prove it wrong. When that anchor moves, the
page is stale and is edited or deleted in the same change. Delete aggressively: a wrong
page is worse than a missing one, because it gets believed.

A bug, in a card or in prose, is stated with real measured values under the six
headings the consuming application's `CLAUDE.md` fixes: what was done, what came back,
why that is wrong, why it happens, the fix, and what the fix produces.

# Citing a page in another repository

A page outside this checkout cannot be a relative link, so it is cited as that
repository's prefix, a colon, a space and the path, inside a code span. The four
prefixes the gate reads are `pathfinder`, `veupathdb-py`, `veupathdb-mcp` and
`assistant-platform`. The gate resolves the path against a checkout of that repository
beside this one, fails when that checkout has no such path, reports the citation as
unverified when there is no checkout to read, and fails on a citation written without
the space wherever it runs. A fenced block holds no code span, so the form is quoted
here rather than cited:

```
veupathdb-py: docs/knowledge/wdk/rules/searches-and-answers.md
```

# Shape

Per OKF v0.2:

- Every non-reserved `.md` carries YAML frontmatter with a non-empty `type`. That is
  the only hard requirement.
- `index.md` and `log.md` are reserved filenames and are not concepts. Only the
  bundle-root `index.md` carries frontmatter, and only `okf_version`.
- A concept's ID is its path within the bundle minus `.md`.
- Cross-links are ordinary markdown links, relative between files.
- `status` is `draft`, `stable` or `deprecated`.

# House style

ASCII punctuation only. No em-dashes, no en-dashes, no curly quotes, no unicode
ellipsis, in prose and in code strings alike.

# The gate script is a copy, on purpose

`scripts/check-knowledge.mjs` and `scripts/check-knowledge.test.mjs`, with the fixtures
under `scripts/__fixtures__/`, are byte-identical copies of the client library's
(`veupathdb-py: scripts/check-knowledge.mjs`), which are themselves copies of the
consuming application's. A change to one copy is made in all of them, in the same
change. The bundle root is an argument with the same default in every repository, so
there is no permitted difference at all.

The repositories share Python distributions, not Node scripts. Publishing a package for
two files of about 400 lines fails YAGNI. Divergence is the cost, and a copy that has
drifted is a gate that passes in one repository and fails in another.
