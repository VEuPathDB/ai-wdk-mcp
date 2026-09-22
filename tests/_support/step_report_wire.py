"""A strategy API whose WDK answers come from memory and whose report bodies are kept."""

from __future__ import annotations

from typing import Any

import pytest
from veupathdb.wdk import StrategyAPI, VEuPathDBClient

REPRESENTATIVE_TRANSCRIPT_ONLY_WIRE = [
    {"name": "representativeTranscriptOnly", "value": {}, "disabled": False}
]


def _answer(record_class_name: str) -> dict[str, Any]:
    return {
        "meta": {
            "totalCount": 1,
            "responseCount": 1,
            "recordClassName": record_class_name,
            "attributes": [],
            "tables": [],
        },
        "records": [
            {
                "displayName": "PF3D7_0100100",
                "id": [{"name": "source_id", "value": "PF3D7_0100100"}],
                "attributes": {},
            }
        ],
    }


class ReportWire:
    """Answers one step of one record type and keeps every report body sent."""

    def __init__(self, record_class_name: str) -> None:
        self._record_class_name = record_class_name
        self.bodies: list[dict[str, Any]] = []

    async def get(self, path: str, **_: object) -> Any:
        del path
        return {
            "id": 9,
            "searchName": "GenesByMolecularWeight",
            "searchConfig": {"parameters": {}},
            "recordClassName": self._record_class_name,
        }

    async def post(
        self, path: str, json: dict[str, Any] | None = None, **_: object
    ) -> Any:
        del path
        self.bodies.append(json or {})
        return _answer(self._record_class_name)


def wire_api(
    monkeypatch: pytest.MonkeyPatch, record_class_name: str
) -> tuple[StrategyAPI, ReportWire]:
    """A real strategy API over an in-memory WDK that answers one record type."""
    client = VEuPathDBClient("https://example.invalid/service")
    wire = ReportWire(record_class_name)
    monkeypatch.setattr(client, "get", wire.get)
    monkeypatch.setattr(client, "post", wire.post)
    return StrategyAPI(client, user_id="1"), wire
