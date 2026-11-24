"""A name read of a vocabulary states the entries a lookup by name cannot reach."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests._support.wdk_reads import serve_reads
from veupathdb.domain.parameters import MultiPickValue, SinglePickValue
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import search_inspection, searches

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "plasmodb_3d7_interpro_vocabulary_half_off.json"
)
SEARCH = "GenesByInterproDomain"


def _recorded() -> WDKSearchResponse:
    record = json.loads(FIXTURE.read_text())
    return WDKSearchResponse.model_validate(record["response_json"])


def _serve(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=_recorded())
    client.get_search_details_with_params = AsyncMock(return_value=_recorded())
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    serve_reads(monkeypatch, _recorded(), client)
    return client


async def test_a_name_read_states_the_entries_it_cannot_reach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch)

    info = await search_inspection.read_parameter_options(
        "plasmodb",
        SEARCH,
        "domain_typeahead",
        record_type="transcript",
        context_values={
            "organism": MultiPickValue(values=["Plasmodium falciparum 3D7"]),
            "domain_database": SinglePickValue(value="INTERPRO"),
        },
        narrowing=search_inspection.VocabNarrowing(query="protein kinase"),
    )

    assert info.kind == "parameter_info"
    assert info.allowed_values_note == (
        "1166 of 4717 entries carry a name of one token past their accession, "
        "and 321 of them carry no name, so a lookup by name does not reach them. "
        "An entry no label names can still be on the site."
    )
