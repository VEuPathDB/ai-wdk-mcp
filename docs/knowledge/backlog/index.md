# Backlog

Everything known to be outstanding, ranked by what unblocks a host other than the first
one. Each item stands alone: a fresh session picks one up without any conversation.

Items are removed when done, not marked done, and their line leaves this file in the
same change. The [log](../log.md) records what left.

## Ranked

1. [The admission lane is evidence, not a gate](the-admission-lane-is-evidence-not-a-gate.md) - a green conformance job on an incomplete verdict, because the exit code and the verdict are two different things.
2. [The server images install the dev group](the-server-images-install-the-dev-group.md) - both images carry mypy, pytest, ruff and 15 more packages no served module imports, because the install stage runs `uv sync` without `--no-dev`.
3. [A clade code names its species count](a-clade-code-names-its-species-count.md) - `lookup_phyletic_codes` returns no species count for a clade, so a model cannot write an OrthoMCL expression for one copy in every species of a clade.
4. [A strain longer than its relatives has a side](a-strain-longer-than-its-relatives-has-a-side.md) - `audit_strain_model` answers `UNCLEAR` for a strain model longer than a reference that sits at its relatives' median, so PVW1_120049800 (2,181 against 1,199, median 1,173) has no side.
