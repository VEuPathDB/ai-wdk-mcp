"""Record every WDK read the fusion check makes for one gene on a QA site, in the order
it makes them, with every gene list upload refused. A whole-genome gene report keeps
only the gene it was read for and the genes beside it on its sequence.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_fusion.py CASE [--models] [--out DIR]``.
"""

import argparse
import asyncio
from pathlib import Path
from typing import NoReturn

from pydantic import BaseModel, ConfigDict
from scripts.record_audit_fixtures import FIXTURES, act_as_the_test_account
from scripts.record_audit_missing import (
    RecordCall,
    SearchCall,
    Tape,
    TapedClient,
    TapedRecords,
    WireCall,
)
from scripts.record_audit_records import RecordingStoppedError, Tally
from veupathdb import JSONObject, set_observer
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import close_all_jbrowse_clients
from veupathdb.wdk import (
    StrategyAPI,
    WDKAnswer,
    WDKRecordInstance,
    WDKSearchConfig,
    close_all_clients,
)

from veupathdb_mcp.audit import gene_ids, gene_models, genes, record_reads
from veupathdb_mcp.audit.fusion import NEIGHBOURS_EACH_SIDE
from veupathdb_mcp.audit.gene_models import MODEL_TABLE, model_record
from veupathdb_mcp.audit.genes import GENOME_SEARCH, GeneRow
from veupathdb_mcp.tools.audit_fusion_tools import audit_gene_fusion


class FusionCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    site: str
    gene: str
    models: list[str] = []


class FusionRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    case: FusionCase
    calls: list[WireCall]


CASES: dict[str, FusionCase] = {
    "pfraNilgiri_rpt6": FusionCase(
        file="fusion_pfraNilgiri_rpt6.json",
        site="plasmodb",
        gene="AK88_02763",
        models=["PCOAH_00051830", "PCOAH_00051820"],
    ),
    "tgonME49_pbgs": FusionCase(
        file="fusion_tgonME49_pbgs.json", site="toxodb", gene="TGME49_500302"
    ),
}
KEPT_EACH_SIDE = NEIGHBOURS_EACH_SIDE + 1
MODEL_BUDGET = 2
WDK_BUDGET = 26


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.sent = 0

    def spend(self, what: str) -> None:
        if self.sent >= self.limit:
            msg = f"the recording spent its {self.limit} WDK reads"
            raise RecordingStoppedError(msg)
        self.sent += 1
        print("read", self.sent, what)


class BudgetRecords:
    def __init__(self, records: TapedRecords, budget: Budget) -> None:
        self._records = records
        self._budget = budget

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        self._budget.spend(f"{record_type} {primary_key[0]['value']} {tables}")
        return await self._records.get_single_record(
            record_type, primary_key, attributes=attributes, tables=tables
        )


class BudgetSearches:
    def __init__(self, client: TapedClient, budget: Budget) -> None:
        self._client = client
        self._budget = budget

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        self._budget.spend(f"{search_name} {search_config.parameters}")
        return await self._client.run_search_report(
            record_type, search_name, search_config, report_config
        )


def _uploaded(*_: object, **__: object) -> NoReturn:
    msg = "the fusion check asked to upload a gene list"
    raise RecordingStoppedError(msg)


def tape_the_record_reads(tape: Tape, budget: Budget) -> None:
    api = gene_models.get_strategy_api
    transcripts = record_reads.get_strategy_api
    client = genes.get_wdk_client
    gene_models.get_strategy_api = lambda site_id: BudgetRecords(
        TapedRecords(api(site_id), tape), budget
    )
    record_reads.get_strategy_api = lambda site_id: BudgetRecords(
        TapedRecords(transcripts(site_id), tape), budget
    )
    genes.get_wdk_client = lambda site_id: BudgetSearches(
        TapedClient(client(site_id), tape), budget
    )
    StrategyAPI.create_dataset = _uploaded
    genes.dataset_client = _uploaded
    record_reads.dataset_client = _uploaded
    gene_ids.genes_by_text = _uploaded


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


def models_read(calls: list[WireCall]) -> list[str]:
    read: list[str] = []
    for call in calls:
        match call:
            case RecordCall(tables=tables, primary_key=key) if MODEL_TABLE in tables:
                read.extend(p["value"] for p in key if p["name"] == "source_id")
            case _:
                pass
    return read


def models_unread(case: FusionCase, calls: list[WireCall]) -> list[str]:
    read = models_read(calls)
    return [gene for gene in case.models if gene not in read]


async def record_models(name: str, into: Path) -> None:
    case = CASES[name]
    held = FusionRecording.model_validate_json((into / case.file).read_text())
    recording = held.model_copy(update={"case": case})
    unread = models_unread(case, held.calls)
    if len(unread) > MODEL_BUDGET:
        msg = f"{len(unread)} models are unread; the recording reads {MODEL_BUDGET}"
        raise ValueError(msg)
    use_qa_sites()
    await act_as_the_test_account()
    tape = Tape()
    api = gene_models.get_strategy_api
    gene_models.get_strategy_api = lambda site_id: TapedRecords(api(site_id), tape)
    try:
        for gene in unread:
            await model_record(case.site, gene)
            print("model", gene, "200")
    finally:
        await close_all_clients()
        print("model reads sent", len(tape.calls))
    write_recording(
        into, recording.model_copy(update={"calls": [*recording.calls, *tape.calls]})
    )


async def record(name: str, into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    tally = Tally()
    set_observer(tally)
    case = CASES[name]
    tape = Tape()
    budget = Budget(WDK_BUDGET)
    tape_the_record_reads(tape, budget)
    try:
        result = await audit_gene_fusion(case.site, case.gene)
    finally:
        await close_all_jbrowse_clients()
        await close_all_clients()
        print("reads sent", budget.sent, "wdk observed", len(tally.wdk))
    centres = {case.gene, *([result.reference_gene] if result.reference_gene else [])}
    write_recording(into, FusionRecording(case=case, calls=trim(tape.calls, centres)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("--out", type=Path, default=FIXTURES)
    parser.add_argument("--models", action="store_true")
    arguments = parser.parse_args()
    if arguments.models:
        asyncio.run(record_models(arguments.case, arguments.out))
    else:
        asyncio.run(record(arguments.case, arguments.out))
