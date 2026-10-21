from pathlib import Path

import pytest
from pydantic import JsonValue
from scripts.record_audit_fixtures import LengthWire
from tests._support.audit_site import Contig, Genome
from veupathdb.wdk import WDKAnswer, WDKRecordInstance

from veupathdb_mcp.audit import gene_models

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"


class ServedRecords:
    def __init__(self, records: list[WDKRecordInstance]) -> None:
        self._records = records
        self.reads: list[list[str]] = []

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        self.reads.append(tables)
        return next(r for r in self._records if sorted(r.tables) == sorted(tables))


def load_wire(name: str) -> LengthWire:
    return LengthWire.model_validate_json((FIXTURES / name).read_text())


def answers(bodies: list[JsonValue]) -> list[WDKAnswer]:
    return [WDKAnswer.model_validate(body) for body in bodies]


def install_records(monkeypatch: pytest.MonkeyPatch, wire: LengthWire) -> ServedRecords:
    records = ServedRecords(
        [WDKRecordInstance.model_validate(body) for body in wire.records]
    )
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: records)
    return records


def install_genome(
    monkeypatch: pytest.MonkeyPatch, wire: LengthWire, abbrev: str, seqid: str
) -> Genome:
    genome = Genome(monkeypatch)
    genome.contigs[abbrev, seqid] = Contig(
        start=wire.window_start, sequence=wire.window, length=wire.contig_length
    )
    return genome
