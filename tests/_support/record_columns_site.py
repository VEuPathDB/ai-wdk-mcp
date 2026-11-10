from __future__ import annotations

import json
from pathlib import Path

import pytest
from veupathdb.wdk import WDKRecordType, WDKSearch, WDKSearchResponse

from veupathdb_mcp.records import columns

FIXTURES = Path(__file__).parents[1] / "unit" / "records" / "fixtures"


def recorded_body(name: str) -> dict[str, object]:
    body: dict[str, object] = json.loads((FIXTURES / name).read_text())["body"]
    return body


def recorded_genes_by_taxon() -> WDKSearch:
    recording = Path(__file__).parents[1] / "unit" / "catalog" / "fixtures"
    wire = json.loads((recording / "plasmodb_genes_by_taxon.json").read_text())
    return WDKSearchResponse.model_validate(wire["response_json"]).search_data


def recorded_record_type(name: str) -> WDKRecordType:
    return WDKRecordType.model_validate(recorded_body(name))


class _Catalog:
    def __init__(self, held: dict[str, list[WDKRecordType]]) -> None:
        self._held = held

    async def get_record_types(self, site_id: str) -> list[WDKRecordType]:
        return self._held.get(site_id, [])

    async def get_searches(self, site_id: str, record_type: str) -> list[WDKSearch]:
        for held in self._held.get(site_id, []):
            if held.url_segment == record_type:
                return held.searches or []
        return []


def serve_recorded_records(monkeypatch: pytest.MonkeyPatch) -> None:
    held = {
        "veupathdb": [
            recorded_record_type("veupathdb_organism_record_type.json"),
            WDKRecordType(
                url_segment="transcript",
                display_name="Gene",
                searches=[recorded_genes_by_taxon()],
            ),
        ],
        "orthomcl": [recorded_record_type("orthomcl_helper_record_type.json")],
    }
    monkeypatch.setattr(columns, "get_discovery_service", lambda: _Catalog(held))
