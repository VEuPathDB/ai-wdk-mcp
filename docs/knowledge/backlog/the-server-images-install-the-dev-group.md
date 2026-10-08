---
type: Backlog
title: The server images install the dev group
description: Both server images carry mypy, pytest, ruff and the rest of the dev dependency group, because the install stage runs uv sync without --no-dev.
tags: [images, dependencies, release]
status: draft
---

# What I did

Read the lock with and without the dev group:
`uv export --frozen --no-hashes --no-emit-project` and the same command with
`--no-dev`. Then listed `.venv/bin` and measured `.venv` inside the two images that
`Dockerfile` and `Dockerfile.research` build.

# What I got

The lock installs 112 packages with the dev group and 94 without it. The 18 extra
packages are the six the `dev` group of `pyproject.toml` names (mypy, pytest,
pytest-asyncio, respx, ruff, testcontainers) and what they pull in, among them `docker`,
`requests` and `urllib3`.

Both images have `mypy`, `pytest` and `ruff` in `.venv/bin`. In each image the mypy
package is 20M, the ruff binary 21M and `_pytest` 1.5M, inside a `.venv` of 314M.

# Why that's wrong

A served image carries a type checker, a test runner, a linter and a container client
that no served module imports. Each extra package is code an image scan reports and a
release must patch, and at least 42M of each image is tooling that never runs there.

# Why it happens

The install stage of `Dockerfile` and `Dockerfile.research` (line 21 of each) runs
`uv sync --frozen --no-install-project`, and `uv sync` installs the `dev` group by
default.

# Fix

Add `--no-dev` to that `uv sync` line in both files; the shared install stage stays the
same text in both, as `tests/unit/test_dockerfiles.py` requires. Add a test there that
fails when the install stage syncs without `--no-dev`. Then build both images, see each
pass its `HEALTHCHECK`, and see the `wdk-conformance` and `research-conformance` lanes
of `.github/workflows/ci.yml` pass.

# What you'd get

Both images install the 94 runtime packages and none of the 18. `.venv/bin` holds no
`mypy`, `pytest` or `ruff`, both health checks pass, both conformance lanes pass, and
the test fails on a `uv sync` that drops `--no-dev`.
