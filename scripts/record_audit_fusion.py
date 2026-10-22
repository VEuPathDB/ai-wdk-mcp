"""Record every WDK read the fusion check makes for one gene on a QA site, in the order
it makes them. A whole-genome gene report keeps only the gene it was read for and the
genes beside it on its sequence.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_fusion.py CASE [--out DIR]``.
"""

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from scripts.record_audit_fixtures import FIXTURES, act_as_the_test_account
from scripts.record_audit_missing import SearchCall, Tape, WireCall, tape_the_reads
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import close_all_jbrowse_clients
from veupathdb.wdk import WDKRecordInstance, close_all_clients

from veupathdb_mcp.audit.fusion import NEIGHBOURS_EACH_SIDE
from veupathdb_mcp.audit.genes import GENOME_SEARCH, GeneRow
from veupathdb_mcp.tools.audit_fusion_tools import audit_gene_fusion


class FusionCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    site: str
    gene: str


class FusionRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    case: FusionCase
    calls: list[WireCall]


CASES: dict[str, FusionCase] = {
    "pfraNilgiri_rpt6": FusionCase(
        file="fusion_pfraNilgiri_rpt6.json", site="plasmodb", gene="AK88_02763"
    ),
    "tgonME49_pbgs": FusionCase(
        file="fusion_tgonME49_pbgs.json", site="toxodb", gene="TGME49_500302"
    ),
}
KEPT_EACH_SIDE = NEIGHBOURS_EACH_SIDE + 1


def _near(centre: GeneRow, genome: list[GeneRow]) -> set[str]:
    contig = sorted(
        (row for row in genome if row.sequence_id == centre.sequence_id),
        key=lambda row: (row.start, row.gene),
    )
    at = [row.gene for row in contig].index(centre.gene)
    near = {
        row.gene
        for row in contig[max(0, at - KEPT_EACH_SIDE) : at + KEPT_EACH_SIDE + 1]
    }
    other = min(
        (row for row in genome if row.sequence_id != centre.sequence_id),
        key=lambda row: (abs(row.start - centre.start), row.gene),
        default=None,
    )
    return near if other is None else near | {other.gene}


def _kept(call: SearchCall, centres: set[str]) -> SearchCall:
    rows = [
        (raw, GeneRow.from_record(WDKRecordInstance.model_validate(raw)))
        for raw in call.records
    ]
    genome = list({row.gene: row for _, row in rows}.values())
    centre = next((row for row in genome if row.gene in centres), None)
    if centre is None:
        msg = f"a genome report holds none of {', '.join(sorted(centres))}"
        raise ValueError(msg)
    near = _near(centre, genome)
    return call.model_copy(
        update={
            "records": [raw for raw, row in rows if row.gene in near],
            "kept": f"{centre.gene}, the {KEPT_EACH_SIDE} genes on each side of it "
            "on its sequence and the gene of another sequence that starts nearest "
            "to it",
        }
    )


def trim(calls: list[WireCall], centres: set[str]) -> list[WireCall]:
    kept: list[WireCall] = []
    for call in calls:
        match call:
            case SearchCall(search_name=search) if search == GENOME_SEARCH:
                kept.append(_kept(call, centres))
            case _:
                kept.append(call)
    return kept


def write_recording(into: Path, recording: FusionRecording) -> None:
    into.mkdir(parents=True, exist_ok=True)
    (into / recording.case.file).write_text(recording.model_dump_json(indent=1) + "\n")


async def record(name: str, into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    case = CASES[name]
    tape = Tape()
    tape_the_reads(tape)
    try:
        result = await audit_gene_fusion(case.site, case.gene)
    finally:
        await close_all_jbrowse_clients()
        await close_all_clients()
    centres = {case.gene, *([result.reference_gene] if result.reference_gene else [])}
    write_recording(into, FusionRecording(case=case, calls=trim(tape.calls, centres)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.case, arguments.out))
