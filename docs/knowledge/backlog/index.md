# Backlog

Everything known to be outstanding, ranked by what unblocks a host other than the first
one. Each item stands alone: a fresh session picks one up without any conversation.

Items are removed when done, not marked done, and their line leaves this file in the
same change. The [log](../log.md) records what left.

## Ranked

1. [The admission lane is evidence, not a gate](the-admission-lane-is-evidence-not-a-gate.md) - a green conformance job on an incomplete verdict, because the exit code and the verdict are two different things.
2. [The server images install the dev group](the-server-images-install-the-dev-group.md) - both images carry mypy, pytest, ruff and 15 more packages no served module imports, because the install stage runs `uv sync` without `--no-dev`.
3. [A strain longer than its relatives has a side](a-strain-longer-than-its-relatives-has-a-side.md) - `audit_strain_model` answers `UNCLEAR` for a strain model longer than a reference that sits at its relatives' median, so PVW1_120049800 (2,181 against 1,199, median 1,173) has no side.
4. [Every recorder reads by record and uploads no dataset](every-recorder-reads-by-record-and-uploads-no-dataset.md) - five recorders under `scripts/` still read genes through `locus_tag_answers` or `proteins_of`, which upload each gene list as a dataset in the test account, so their wires do not hold the record reads the checks send.
5. [A parameter says it takes pasted text](a-parameter-says-it-takes-pasted-text.md) - ParameterInfo drops WDK's isMultiLine, so a host reads the raw search definition to tell pasted text from a short value.
