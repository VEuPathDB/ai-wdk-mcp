from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel, ConfigDict
from scripts.record_audit_records import (
    RecordExchange,
    RecordWire,
    StoreExchange,
    read_wire,
)
from veupathdb.errors import WDKError
from veupathdb.jbrowse import BigWigReader, GenomeReader, JBrowseClient, TabixReader
from veupathdb.wdk import WDKRecordInstance, get_site

from veupathdb_mcp.audit import (
    gene_models,
    intron_coverage,
    introns_inputs,
    record_reads,
    track_reads,
)

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"
RECORD_ROW = record_reads._row
RECORD_PROTEIN = record_reads._protein

type RecordKey = tuple[
    str, tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]
]


def load_records(name: str) -> RecordWire:
    return read_wire(FIXTURES / name)


class _Id(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: list[dict[str, str]]


def _source(exchange: RecordExchange) -> str:
    parts = _Id.model_validate(exchange.body).id
    return next(part["value"] for part in parts if part["name"] == "source_id")


def record_key(
    record_type: str,
    primary_key: dict[str, str],
    attributes: list[str],
    tables: list[str],
) -> RecordKey:
    return (
        record_type,
        tuple(sorted(primary_key.items())),
        tuple(attributes),
        tuple(tables),
    )


class RecordedRecords:
    def __init__(self, *wires: RecordWire) -> None:
        recorded = [r for wire in wires for r in wire.records]
        self._served: dict[RecordKey, RecordExchange] = {
            record_key(r.record_type, r.primary_key, r.attributes, r.tables): r
            for r in recorded
        }
        self._resolved = {
            r.primary_key["source_id"]: served
            for r in recorded
            if r.status == 200 and (served := _source(r)) != r.primary_key["source_id"]
        }
        self._refused = {
            (r.record_type, r.primary_key["source_id"]): r
            for r in recorded
            if r.status != 200
        }
        self.reads: list[tuple[str, str, tuple[str, ...]]] = []
        self.served: list[RecordKey] = []

    def _answer(
        self,
        record_type: str,
        key: dict[str, str],
        attributes: list[str],
        tables: list[str],
    ) -> RecordExchange:
        own = key["source_id"]
        resolved = {**key, "source_id": self._resolved.get(own, own)}
        found = self._served.get(
            record_key(record_type, key, attributes, tables)
        ) or self._served.get(record_key(record_type, resolved, attributes, tables))
        return found if found is not None else self._refused[record_type, own]

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str] | None = None,
        tables: list[str] | None = None,
    ) -> WDKRecordInstance:
        key = {part["name"]: part["value"] for part in primary_key}
        served = self._answer(
            record_type, key, list(attributes or []), list(tables or [])
        )
        self.reads.append((record_type, key["source_id"], tuple(tables or [])))
        self.served.append(
            record_key(
                served.record_type, served.primary_key, served.attributes, served.tables
            )
        )
        if served.status != 200:
            raise WDKError(str(served.body), status=served.status)
        return WDKRecordInstance.model_validate(served.body)


def install_recorded_records(
    monkeypatch: pytest.MonkeyPatch, *wires: RecordWire
) -> RecordedRecords:
    records = RecordedRecords(*wires)
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: records)
    monkeypatch.setattr(record_reads, "get_strategy_api", lambda site_id: records)
    monkeypatch.setattr(record_reads, "_row", RECORD_ROW)
    monkeypatch.setattr(record_reads, "_protein", RECORD_PROTEIN)
    return records


class ReplayStore(httpx.AsyncBaseTransport):
    def __init__(self, exchanges: list[StoreExchange]) -> None:
        self._served = {(e.url, e.byte_range): e for e in exchanges}
        self.served: list[tuple[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = (str(request.url), request.headers.get("Range", ""))
        exchange = self._served[key]
        self.served.append(key)
        return httpx.Response(exchange.status, content=exchange.body, request=request)


def install_store(monkeypatch: pytest.MonkeyPatch, wire: RecordWire) -> ReplayStore:
    store = ReplayStore(wire.store)
    client = JBrowseClient(base_url=get_site(wire.site).web_base_url, transport=store)
    monkeypatch.setattr(introns_inputs, "get_jbrowse_client", lambda site_id: client)
    monkeypatch.setattr(track_reads, "TabixReader", TabixReader)
    monkeypatch.setattr(track_reads, "GenomeReader", GenomeReader)
    monkeypatch.setattr(intron_coverage, "BigWigReader", BigWigReader)
    return store


class _Protein(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attributes: dict[str, str]


def transcript_proteins(wire: RecordWire) -> dict[str, str]:
    return {
        r.primary_key["gene_source_id"]: _Protein.model_validate(r.body)
        .attributes["protein_sequence"]
        .rstrip("*")
        for r in wire.records
        if r.record_type == "transcript" and r.status == 200
    }
