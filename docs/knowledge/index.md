---
okf_version: "0.2"
---

# veupathdb-mcp Knowledge Bundle

What this repository's two servers owe a host that is not the application they were
written beside, in [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) v0.2. Plain markdown with YAML frontmatter, no tooling required.

The bundle rule: a page here is falsifiable and something falsifies it. Every page names
the file, the test or the command that would prove it wrong, and a page whose anchor moves
is edited or deleted in the same change that moved it. Backlog items are removed when the
work is done, never marked done, and their line leaves `backlog/index.md` in the same
change, so the backlog is exactly what remains at all times. Nothing here restates what
this repository's code or `README.md` already says, and nothing here restates a rule the
consuming application states about itself. `node scripts/check-knowledge.mjs` fails the
build on a concept without a `type`, a link that does not resolve, a concept no index
links to, and non-ASCII punctuation.

## Backlog

- [Backlog](backlog/) - everything outstanding, ranked by what unblocks a second host first

## Decisions

- [Decisions](decisions/) - choices with a real alternative, each naming what was rejected

## Conventions

- [Conventions](conventions/) - how this bundle is kept honest

## History

- [log.md](log.md) - dated record of significant changes to this bundle
