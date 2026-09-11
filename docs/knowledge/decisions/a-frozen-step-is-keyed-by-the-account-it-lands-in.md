---
type: Decision
title: A frozen step is keyed by the account it lands in
description: The process-global cache of materialized gene-set steps keys by a digest of the request's own WDK token, not by the verified credential's subject, because the token is what decides which account holds the new step.
tags: [wdk, identity, cache, gene-sets]
status: stable
---

# The choice

`frozen_step_id` remembers the step it built under
`frozen_step_cache_key(account, site_id, gene_ids)`, where `account` is a digest of the
WDK token the call runs under (`veupathdb_mcp/wdk/gene_set_steps.py`). A call that
carries no token is refused with `WDKLoginRequiredError` rather than keyed as anybody.

A step id names a step inside one WDK account. A cache that keyed by site and membership
alone answered the second caller with the first caller's step id, and every read of that
id afterwards - a size, a sample, its gene ids, a control run - either fails on the
owner's behalf or reports a set the caller never built.

# Why the token names the account

The client resolves one request's token from `veupathdb_auth_token_ctx` and refuses a
path under `/users/` when there is none
(`veupathdb-py: src/veupathdb/wdk/_http.py`, `_effective_token`). So the token is what
decides which account the step is created in, and it is present on both entry paths:
the served layer sets it per call from the credential the transport verified, and a host
that calls in process sets it per request. Nothing has to be passed, and no call site can
pass the wrong thing.

# What was rejected

**Keying by `McpCredential.client_id`.** It is the VEuPathDB subject in user mode, which
is the account, but the application id in service mode, which is not; and only the served
layer has a credential at all. An in-process host would have to pass an account argument
that a caller can forget or fill with a constant, and the failure of that argument is
silent and cross-account.

**Reading the WDK user id from `GET /users/current`.** One extra round trip per call to
name what the token already decides, on a call whose whole point is to avoid rebuilding
a step.

**Dropping the cache on the served path only.** The defect is in the key, not in the
transport. An in-process host serving two signed-in users would keep handing them each
other's steps.

# What it costs

Two tokens for one account key two entries, so that account gets a second step holding
the same genes. A step more in the caller's own account is the tolerable error; a step
in somebody else's is not.

Falsified by
`tests/unit/wdk/test_frozen_gene_set_step.py::TestTheStepIsHeldByAnInternalStrategy::test_another_account_gets_a_step_of_its_own`
and by the served pair in `tests/unit/server/test_server.py`.
