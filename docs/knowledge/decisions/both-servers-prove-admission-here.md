---
type: Decision
title: Both servers prove admission here
description: CI runs the conformance suite against the WDK server on 8100 and the research server on 8110, at one pin, because a service secret is issued by the deployment and needs no VEuPathDB account.
tags: [ci, conformance, generality]
status: stable
---

# The choice

`.github/workflows/ci.yml` carries two admission lanes, `research-conformance` and
`wdk-conformance`, both at the conformance tag the consuming application installs. Each
starts its server, runs `pytest --pyargs mcp_conformance` against it, and uploads the
admission report it wrote.

# Why the WDK lane runs here at all

Admission in service mode needs no VEuPathDB account: the secret is issued by the
deployment that serves, so `WDK_MCP_SERVICE_TOKENS` is a lane-local value. The lane
also reaches no site, for two measured reasons: the server preloads no catalog and
opens no database, and the suite calls a tool only with the arguments the runner
supplies. The runner here supplies none, so the one family that calls tools sends the
bad argument its own schema refuses, and the site guard refuses it before any read.

Measured on the served endpoint at this version: 24 checks pass, 8 skip, no check
fails, with 25 tools in the report.

# What the skips are

Three families need something a runner supplies rather than something a server states:
an account-state hook (family 3), a second identity and a resource it owns (family 2),
and a tool slow enough to drive past its budget (family 5). The verdict is
`incomplete` for that reason, on both lanes. A lane that supplies them reads the same
server more deeply; it does not make this one less true.

# What was rejected

**Leaving the 8100 lane in the consuming application.** That lane needs that
application's database, because a user bearer there names a row in its own schema, so
a second host can neither run it nor tell whether a failure is the server's. It stays
where it is and now tests that application's own identity wiring, which is the only
part of it this repository cannot prove.

**A scheduled live-site lane for admission.** A live site would be needed only to give
the suite sample arguments for the account-state family. That is a deeper read of the
same server, not the admission gate, and it would put a credential and a site outage
between a push and a green build.
