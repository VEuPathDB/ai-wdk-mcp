# Backlog

Everything known to be outstanding, ranked by what unblocks a host other than the first
one. Each item stands alone: a fresh session picks one up without any conversation.

Items are removed when done, not marked done, and their line leaves this file in the
same change. The [log](../log.md) records what left.

## Ranked

1. [The admission lane is evidence, not a gate](the-admission-lane-is-evidence-not-a-gate.md) - a green conformance job on an incomplete verdict, because the exit code and the verdict are two different things.
2. [The server images install the dev group](the-server-images-install-the-dev-group.md) - both images carry mypy, pytest, ruff and 15 more packages no served module imports, because the install stage runs `uv sync` without `--no-dev`.
3. [The production recordings are recorded again on QA](the-production-recordings-are-recorded-again-on-qa.md) - fourteen recordings made on production moved out of the tests, and the tests that read them are skipped until QA answers automated clients.
