from __future__ import annotations

import pytest
from scripts.record_audit_records import RecordExchange, RecordWire
from scripts.record_orthomcl_gene_class import FILE, FIXTURES, GeneClassWire
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKRecordType, get_site

from veupathdb_mcp.catalog import gene_records

ORTHOMCL_RECORDING = FIXTURES / FILE


def plasmodb_record_types() -> list[str]:
    recorded = load_recorded("record_types")
    assert recorded.provenance.site == "plasmodb"
    return [str(name) for name in recorded.json_body()]


def orthomcl_wire() -> GeneClassWire:
    return GeneClassWire.model_validate_json(ORTHOMCL_RECORDING.read_text())


def orthomcl_record_types() -> list[str]:
    return [str(name) for name in orthomcl_wire().record_types.response_json]


def recorded_record_types(site_id: str) -> list[str]:
    match site_id:
        case "plasmodb":
            return plasmodb_record_types()
        case "orthomcl":
            return orthomcl_record_types()
        case _:
            msg = f"no recording lists the record types of {site_id}"
            raise AssertionError(msg)


class _SiteRecordTypes:
    def __init__(self, served: RecordedRecordTypes, site_id: str) -> None:
        self._served = served
        self._site_id = site_id

    async def get_record_types(self) -> list[WDKRecordType]:
        self._served.asked.append(self._site_id)
        return [
            WDKRecordType(url_segment=name)
            for name in recorded_record_types(self._site_id)
        ]


class RecordedRecordTypes:
    def __init__(self, held: list[str]) -> None:
        self.held = held
        self.asked: list[str] = []
        self.catalog_asked: list[str] = []

    def held_record_types(self, site_id: str) -> list[WDKRecordType] | None:
        if site_id not in self.held:
            return None
        self.catalog_asked.append(site_id)
        return [
            WDKRecordType(url_segment=name) for name in recorded_record_types(site_id)
        ]

    def client(self, site_id: str) -> _SiteRecordTypes:
        return _SiteRecordTypes(self, site_id)


def serve_record_types(
    monkeypatch: pytest.MonkeyPatch, held: list[str] | None = None
) -> RecordedRecordTypes:
    served = RecordedRecordTypes(held or [])
    monkeypatch.setattr(gene_records, "_LISTED", {})
    monkeypatch.setattr(gene_records, "get_discovery_service", lambda: served)
    monkeypatch.setattr(gene_records, "get_wdk_client", served.client)
    return served


def orthomcl_gene_read() -> RecordWire:
    wire = orthomcl_wire()
    read = wire.gene_record
    return RecordWire(
        site=wire.site,
        transcript_key=[],
        records=[
            RecordExchange(
                record_type="gene",
                primary_key={
                    "source_id": wire.gene,
                    "project_id": get_site(wire.site).project_id,
                },
                attributes=[],
                tables=[],
                status=read.status,
                body=read.response_json
                if read.response_json is not None
                else read.response_text,
            )
        ],
    )
