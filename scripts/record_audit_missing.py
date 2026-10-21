"""Record every WDK and genome read the missing-gene check makes for one case on a QA
site, in the order it makes them. A whole-genome gene report keeps only the records the
check can use: the example and the genes the anchor walk passes on each side of it, and
the absent genome's records in the groups of those genes or inside the window read.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_missing.py CASE [--out DIR]``.
"""

import argparse
import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, JsonValue
from scripts.record_audit_fixtures import FIXTURES
from veupathdb import JSONObject
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import (
    GenomeReader,
    GenomeWindow,
    JBrowseClient,
    close_all_jbrowse_clients,
)
from veupathdb.testing.wdk_credentials import act_as_the_test_account
from veupathdb.wdk import (
    StrategyAPI,
    VEuPathDBClient,
    WDKAnswer,
    WDKDatasetConfigIdList,
    WDKRecordInstance,
    WDKSearchConfig,
    close_all_clients,
)

from veupathdb_mcp.audit import gene_models, genes, missing_inputs
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.lengths import is_orthology_group
from veupathdb_mcp.audit.missing import ANCHOR_REACH
from veupathdb_mcp.tools.audit_missing_tools import audit_missing_gene


class DatasetCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["dataset"] = "dataset"
    ids: list[str]
    dataset: int


class SearchCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["search"] = "search"
    record_type: str
    search_name: str
    parameters: dict[str, str]
    report: JSONObject | None
    records: list[JSONObject]
    served_total: int
    kept: str | None = None

    @property
    def total(self) -> int:
        return self.served_total if self.kept is None else len(self.records)


class RecordCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["record"] = "record"
    record_type: str
    primary_key: list[dict[str, str]]
    attributes: list[str]
    tables: list[str]
    record: JsonValue


class WindowCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["window"] = "window"
    abbrev: str
    seqid: str
    start: int
    end: int
    served_start: int
    sequence: str


type WireCall = Annotated[
    DatasetCall | SearchCall | RecordCall | WindowCall, Discriminator("kind")
]


class MissingCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    site: str
    example_gene: str
    absent_organism: str


class MissingRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    case: MissingCase
    calls: list[WireCall]


CASES: dict[str, MissingCase] = {
    "tgonGT1_nac": MissingCase(
        file="missing_tgonGT1_nac.json",
        site="toxodb",
        example_gene="TGARI_257090",
        absent_organism="Toxoplasma gondii GT1",
    ),
}


class Tape:
    def __init__(self) -> None:
        self.calls: list[WireCall] = []


class TapedClient:
    def __init__(self, client: VEuPathDBClient, tape: Tape) -> None:
        self.client = client
        self.tape = tape

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        answer = await self.client.run_search_report(
            record_type, search_name, search_config, report_config
        )
        self.tape.calls.append(
            SearchCall(
                record_type=record_type,
                search_name=search_name,
                parameters=search_config.parameters,
                report=report_config,
                records=[
                    r.model_dump(mode="json", by_alias=True) for r in answer.records
                ],
                served_total=answer.meta.total_count or 0,
            )
        )
        return answer


class TapedDatasets:
    def __init__(self, client: TapedClient) -> None:
        self.api = StrategyAPI(client.client)
        self.tape = client.tape

    async def create_dataset(self, config: WDKDatasetConfigIdList) -> int:
        dataset = await self.api.create_dataset(config)
        self.tape.calls.append(
            DatasetCall(ids=config.source_content.ids, dataset=dataset)
        )
        return dataset


class TapedRecords:
    def __init__(self, api: StrategyAPI, tape: Tape) -> None:
        self.api = api
        self.tape = tape

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        record = await self.api.get_single_record(
            record_type, primary_key, attributes=attributes, tables=tables
        )
        self.tape.calls.append(
            RecordCall(
                record_type=record_type,
                primary_key=primary_key,
                attributes=attributes,
                tables=tables,
                record=record.model_dump(mode="json", by_alias=True),
            )
        )
        return record


class TapedReader:
    def __init__(self, client: JBrowseClient, tape: Tape) -> None:
        self.reader = GenomeReader(client)
        self.tape = tape

    async def window(
        self, abbrev: str, seqid: str, start: int, end: int
    ) -> GenomeWindow:
        window = await self.reader.window(abbrev, seqid, start, end)
        self.tape.calls.append(
            WindowCall(
                abbrev=abbrev,
                seqid=seqid,
                start=start,
                end=end,
                served_start=window.start,
                sequence=window.sequence,
            )
        )
        return window


def tape_the_reads(tape: Tape) -> None:
    shared = genes.get_wdk_client
    private = genes.dataset_client
    records = gene_models.get_strategy_api

    @asynccontextmanager
    async def taped_private(site_id: str) -> AsyncIterator[TapedClient]:
        async with private(site_id) as client:
            yield TapedClient(client, tape)

    genes.get_wdk_client = lambda site_id: TapedClient(shared(site_id), tape)
    genes.dataset_client = taped_private
    genes.StrategyAPI = TapedDatasets
    gene_models.get_strategy_api = lambda site_id: TapedRecords(records(site_id), tape)
    missing_inputs.GenomeReader = lambda client: TapedReader(client, tape)


TAXON = "GenesByTaxon"


def _genes(call: SearchCall) -> list[tuple[JSONObject, GeneRow]]:
    return [
        (raw, GeneRow.from_record(WDKRecordInstance.model_validate(raw)))
        for raw in call.records
    ]


def _keep(
    call: SearchCall, rows: list[tuple[JSONObject, GeneRow]], why: str
) -> SearchCall:
    return call.model_copy(update={"records": [raw for raw, _ in rows], "kept": why})


def _anchor_window(calls: list[WireCall]) -> WindowCall | None:
    for call in reversed(calls):
        match call:
            case WindowCall():
                return call
            case _:
                pass
    return None


def _taxon(call: WireCall) -> SearchCall | None:
    match call:
        case SearchCall(search_name="GenesByTaxon"):
            return call
        case _:
            return None


def _absent_kept(
    call: SearchCall, groups: set[str], window: WindowCall | None
) -> SearchCall:
    inside = [
        (raw, row)
        for raw, row in _genes(call)
        if row.ortholog_group in groups
        or (
            window is not None
            and row.sequence_id == window.seqid
            and row.end >= window.served_start
            and row.start <= window.served_start + len(window.sequence) - 1
        )
    ]
    return _keep(
        call, inside, "records in the kept example genes' groups or the window"
    )


def _example_kept(case: MissingCase, call: SearchCall) -> SearchCall:
    rows = _genes(call)
    example = next(row for _, row in rows if row.gene == case.example_gene)
    contig = sorted(
        ((raw, row) for raw, row in rows if row.sequence_id == example.sequence_id),
        key=lambda pair: (pair[1].start, pair[1].gene),
    )
    at = next(i for i, (_, row) in enumerate(contig) if row.gene == example.gene)
    near = contig[max(0, at - ANCHOR_REACH) : at + ANCHOR_REACH + 1]
    return _keep(
        call,
        near,
        f"the example and the {ANCHOR_REACH} genes on each side of it",
    )


def trim(case: MissingCase, calls: list[WireCall]) -> list[WireCall]:
    absent = json.dumps([case.absent_organism])
    taxa = [taxon for call in calls if (taxon := _taxon(call)) is not None]
    example = next(
        (_example_kept(case, t) for t in taxa if t.parameters["organism"] != absent),
        None,
    )
    if example is None:
        return calls
    groups = {
        row.ortholog_group
        for _, row in _genes(example)
        if is_orthology_group(row.ortholog_group)
    }
    window = _anchor_window(calls)
    kept: list[WireCall] = []
    for call in calls:
        match _taxon(call):
            case None:
                kept.append(call)
            case taxon if taxon.parameters["organism"] == absent:
                kept.append(_absent_kept(taxon, groups, window))
            case _:
                kept.append(example)
    return kept


def write_recording(into: Path, recording: MissingRecording) -> None:
    into.mkdir(parents=True, exist_ok=True)
    (into / recording.case.file).write_text(recording.model_dump_json(indent=1) + "\n")


async def record(name: str, into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    case = CASES[name]
    tape = Tape()
    tape_the_reads(tape)
    try:
        await audit_missing_gene(case.site, case.example_gene, case.absent_organism)
    finally:
        await close_all_jbrowse_clients()
        await close_all_clients()
    write_recording(into, MissingRecording(case=case, calls=trim(case, tape.calls)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.case, arguments.out))
