---
type: Backlog
title: The admission lane is evidence, not a gate
description: The wdk-conformance and research-conformance jobs are green on an incomplete verdict, because CI reads pytest's exit code while the verdict lives in the uploaded artifact.
tags: [ci, conformance, gates]
status: draft
---

# What I did

Started this checkout's WDK server on a local port with `WDK_MCP_BASE_URL` and
`WDK_MCP_SERVICE_TOKENS` set the way `.github/workflows/ci.yml` sets them, installed
the conformance suite at the tag both lanes pin, and ran the lane's own command:
`pytest --pyargs mcp_conformance -q -rs --mcp-report admission-report.json`.

# What I got

24 checks passed, 8 skipped, no check failed, 25 tools in the report, and
`"verdict": "incomplete"` in `admission-report.json`. **pytest exited 0**, so the CI
step is green.

Two families are already mostly unrun: annotations passes 2 of its 5 checks and
timeouts passes 1 of its 4. The other checks in them skip because the runner names no
slow tool, no sample arguments, no account-state hook and no second identity.

# Why that's wrong

The job says the server is admissible and the artifact says the run was incomplete. A
change that turned the 2 passing annotation checks or the 1 passing timeout check into
skips would keep the build green, and the lane would report admission for a server that
proved less than it does today. The lane exists to catch exactly that regression, and
for the families that skip it cannot.

# Why it happens

The suite writes the verdict into the report file and prints one summary line; nothing
in it touches the pytest session's exit status, and a skipped check exits 0
(`assistant-platform: packages/mcp-conformance/src/mcp_conformance/_report.py`, the
verdict and the terminal summary).

# Fix

Not fixable here as things stand: the eight skips need a VEuPathDB account, a slow tool
and a second identity that this repository's CI has none of. When a lane has an account,
supply `--mcp-slow-tool`, sample arguments for a non-destructive tool, an account-state
hook and `--mcp-bearer-second` with `--mcp-isolation-tool`, then fail the job unless the
report reads `"verdict": "pass"`, in both lanes.

Until then the lanes stay as they are and
[both servers prove admission here](../decisions/both-servers-prove-admission-here.md)
states what they do and do not prove.

# What you'd get

A green admission lane that means every family ran, and a red one when a future change
stops a family from running at all.
