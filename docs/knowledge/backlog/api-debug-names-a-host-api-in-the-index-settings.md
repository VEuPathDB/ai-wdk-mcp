---
type: Backlog
title: api_debug names a host API in the index settings, and collides with one
description: The embedding settings declare api_debug for SQLAlchemy echo; the assistant runtime declares the same field name, so a host that inherits both has one flag driving two engines.
tags: [coupling, settings, embeddings]
status: draft
---

# What I did

Read `src/veupathdb_mcp/embeddings/settings.py` and its one reader,
`src/veupathdb_mcp/embeddings/db.py`, then read the settings class that installs itself
as this package's settings source:
`pathfinder: apps/api/src/pathfinder/platform/config.py`.

# What I got

- `embeddings/settings.py:26`: `api_debug: bool = False`. It is the only field of the
  model that names no part of the embedder; the others are `database_url`,
  `openai_api_key`, `embedding_backend`, `embedding_model`,
  `embedding_request_concurrency`, `embedding_batch_size` and
  `embedding_input_char_limit`, and `tests/unit/embeddings/test_index_ownership.py:30`
  pins that set.
- `embeddings/db.py:34`: `echo=settings.api_debug`, on the engine the index builds on
  first use.
- `config.py:88` in the consuming application:
  `class Settings(RuntimeSettings, VEuPathDBSettings, McpSettings, EmbeddingSettings)`,
  and `config.py:310` installs it with `use_embedding_settings_source(get_settings)`.
- The assistant runtime declares the same field name:
  `assistant-platform: packages/assistant-core/src/assistant_core/platform/config.py`
  line 29, read at its `platform/db.py` line 39 for the same purpose on the host's own
  engine.
- The application sets it once, `api_debug = false` in `pathfinder: apps/api/config.toml`.

# Why that's wrong

The two declarations have the same name, so a host that inherits both gets one field.
An operator who turns on `API_DEBUG` to read the application's own SQL also turns on
statement echo inside this package's index engine, and every vector write and every
similarity query is printed into that deployment's logs. There is no setting that
separates them, because the collision is in the field name and the host has only one
slot for it. A second host reads `API_DEBUG` in the embedding settings as its API's flag
and is right about the name and wrong about the effect.

# Why it happens

The embedding settings were split out of a host application's settings model, where
`api_debug` was that application's flag. The field came across with its name intact
because the one call site kept working, and the model is inherited rather than composed,
so the duplicate name silently merged instead of failing.

# Fix

In this repository, in the release that follows `0.2.0a4`: rename the field to
`embedding_sql_echo`, keep the default, update `embeddings/db.py:34`, update the pinned
field set at `tests/unit/embeddings/test_index_ownership.py:30`, and add the row to the
README's embedding variables table. No alias: the name is the collision.

When the consuming application takes the tag, `api_debug` keeps driving its own engine
alone, and a deployment that wants the index echo sets `EMBEDDING_SQL_ECHO`. Nothing in
the application has to change for it to build.

# What you'd get

Two flags for two engines: the host's SQL echo stays the host's, the index's echo is
named after the index, and every field of the embedding settings describes the embedder
or its database.
