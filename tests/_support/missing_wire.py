from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from scripts.record_audit_missing import (
    DatasetCall,
    MissingRecording,
    RecordCall,
    SearchCall,
    WindowCall,
    WireCall,
)
from veupathdb import JSONObject
from veupathdb.jbrowse import GenomeWindow
from veupathdb.wdk import (
    WDKAnswer,
    WDKDatasetConfigIdList,
    WDKRecordInstance,
    WDKSearchConfig,
)

from veupathdb_mcp.audit import gene_models, genes, missing_inputs

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"


def recording(name: str) -> MissingRecording:
    return MissingRecording.model_validate_json((FIXTURES / name).read_text())


class WireReplay:
    def __init__(self, calls: list[WireCall]) -> None:
        self.calls: list[WireCall] = list(calls)

    def _next(self) -> WireCall:
        assert self.calls, "the check read more than the recording holds"
        return self.calls.pop(0)

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        match self._next():
            case SearchCall() as call:
                assert (call.record_type, call.search_name) == (
                    record_type,
                    search_name,
                )
                assert (call.parameters, call.report) == (
                    search_config.parameters,
                    report_config,
                )
                return WDKAnswer.model_validate(
                    {
                        "meta": {
                            "totalCount": call.total,
                            "responseCount": len(call.records),
                        },
                        "records": call.records,
                    }
                )
            case other:
                raise AssertionError(other)

    async def create_dataset(self, config: WDKDatasetConfigIdList) -> int:
        match self._next():
            case DatasetCall() as call:
                assert call.ids == config.source_content.ids
                return call.dataset
            case other:
                raise AssertionError(other)

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        match self._next():
            case RecordCall() as call:
                assert (call.record_type, call.primary_key) == (
                    record_type,
                    primary_key,
                )
                assert (call.attributes, call.tables) == (attributes, tables)
                return WDKRecordInstance.model_validate(call.record)
            case other:
                raise AssertionError(other)

    async def window(
        self, abbrev: str, seqid: str, start: int, end: int
    ) -> GenomeWindow:
        match self._next():
            case WindowCall() as call:
                assert (call.abbrev, call.seqid, call.start, call.end) == (
                    abbrev,
                    seqid,
                    start,
                    end,
                )
                return GenomeWindow(
                    seqid=seqid, start=call.served_start, sequence=call.sequence
                )
            case other:
                raise AssertionError(other)


def replay(monkeypatch: pytest.MonkeyPatch, calls: list[WireCall]) -> WireReplay:
    wire = WireReplay(calls)

    @asynccontextmanager
    async def opened(site_id: str) -> AsyncIterator[WireReplay]:
        yield wire

    monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: wire)
    monkeypatch.setattr(genes, "dataset_client", opened)
    monkeypatch.setattr(genes, "StrategyAPI", lambda client: wire)
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: wire)
    monkeypatch.setattr(missing_inputs, "get_jbrowse_client", lambda site_id: wire)
    monkeypatch.setattr(missing_inputs, "GenomeReader", lambda client: client)
    return wire
