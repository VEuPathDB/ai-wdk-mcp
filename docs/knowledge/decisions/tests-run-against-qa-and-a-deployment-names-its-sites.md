---
type: Decision
title: Tests run against QA, and a deployment names its site list
description: Every test and every recorder in this repository reads the QA site list the client library ships, no recording made on production stays where a test reads it, and the server serves only the list VEUPATHDB_SITES_CONFIG names. Production and beta were rejected for tests because test load reached the production servers.
tags: [testing, sites, live-lane, recording, ci]
status: stable
---

# What was decided

- **The site list.** The client library ships no default list, so this server reads the
  file `VEUPATHDB_SITES_CONFIG` names and fails at its first site read without one. A
  deployment always chooses its sites.
- **Every test reads QA.** `tests/conftest.py` sets `VEUPATHDB_SITES_CONFIG` to
  `veupathdb.testing.QA_SITES_FILE` for every test, the `live_wdk` lane included. The
  QA hosts are `qa.<site>.org/<project>.qa/service`.
- **Recording reads QA only.** `scripts/record_all_datasets.py` installs the QA list
  through `veupathdb.devtools.use_qa_sites` before it posts, whatever the environment
  names. No option points it at another list.
- **Every recording a test reads is a QA recording.** A test whose recording is absent is
  skipped with `veupathdb.testing.NEEDS_QA_RECORDING` while `needs_qa_recording` finds it
  absent, so a QA recording lifts the skip with no change to the test. The attributes a
  record type declares are read from `tests/unit/fixtures/gene_record_attributes.json`,
  recorded on QA, and not from the warm cache.
- **The guard.** `scripts/check-test-sites.mjs` fails on a production host (a site
  domain whose nearest label is not `qa` or `q2`: bare, `www.`, `beta.`, a numbered
  server or any other subdomain) in any file outside `README.md`, `data/catalogs/` and
  `docs/`. It is the client library's script with its own
  allowlist. CI and pre-commit run it with its test.
- **CI.** The WDK admission lane serves the QA list the client ships. The `live` job
  runs only on a schedule, and the workflow names none, so no job reaches a site.

# Rejected

- **Production.** Test load on a production site reaches the researchers who use it.
- **Beta.** `beta.<site>.org` is served by the production servers.
- **A default list in the client library.** A process that forgot to name its sites
  reached production silently.
- **An option that lets a recorder reach production.** No recording needs it.

# What this costs

The `data/catalogs/` snapshot is production data the image serves as a warm cache; it
stays, and no test reads it. The client library's cached AI expression summary has no QA
recording, so the tests that read it are skipped.

# What proves it wrong

`node scripts/check-test-sites.mjs`, `tests/unit/test_the_dataset_recorder_asks_the_qa_site.py`,
and `uv run pytest tests/unit -rs`, which names every skipped test.
