---
type: Backlog
title: The production recordings are recorded again on QA
description: Fourteen recordings made on production sites moved to fixtures-production-backup-2026-10-09/, and the tests that read them, with those that read the client library's moved recordings and the data/catalogs snapshot, are skipped with NEEDS_QA_RECORDING.
tags: [testing, recording, sites]
status: draft
---

# What is missing

The recordings under `fixtures-production-backup-2026-10-09/tests/unit/` were made on
production: ten under `catalog/fixtures/`, three under `separation/fixtures/` and one
under `wdk/fixtures/`. Each is recorded again on the QA site its provenance names and
written back to its old path. The client library's recorded WDK bodies are recorded
again in that repository.

# What it blocks

Every test marked `pytest.mark.skip(reason=NEEDS_QA_RECORDING)`;
`uv run pytest tests/unit -rs` lists them. A test that reads `data/catalogs/` is
skipped too, because that snapshot was built on production.

# How to finish

QA answers automated clients first: outside the VEuPathDB network the QA sites answer
with a pre-release login. Then record each file on QA (`scripts/record_all_datasets.py`
for the two AllDatasets reports; the provenance of the others names the request),
re-measure every count a test pins, drop the skip markers, delete the backup directory,
and remove this item and its line.
