"""Two recorded Pfam vocabularies of ``GenesByInterproDomain``, served by a stub client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests._support.wdk_reads import serve_reads
from veupathdb.domain.parameters import ParamValue, SinglePickValue
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import searches

FIXTURES = Path(__file__).parent / "fixtures"
DAL972 = "tritrypdb_dal972_pfam_refresh"
FOWLERI = "amoebadb_nfowleri_pfam_refresh"
SEARCH = "GenesByInterproDomain"
PARAMETER = "domain_typeahead"
CONTEXT: dict[str, ParamValue] = {"domain_database": SinglePickValue(value="Pfam")}


def _domain_database() -> dict[str, object]:
    """The database parameter ``GenesByInterproDomain`` publishes, as recorded."""
    body = json.loads(
        (FIXTURES / "plasmodb_3d7_interpro_vocabulary_half_off.json").read_text()
    )
    [declared] = [
        p
        for p in body["response_json"]["searchData"]["parameters"]
        if p["name"] == "domain_database"
    ]
    return declared


def refresh_parameters(name: str) -> list[dict[str, object]]:
    body: dict[str, list[dict[str, object]]] = json.loads(
        (FIXTURES / f"{name}.json").read_text()
    )
    return body["response_json"]


def serve(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Answer every read of the search with the recorded refresh."""
    response = WDKSearchResponse.model_validate(
        {
            "searchData": {
                "urlSegment": SEARCH,
                "parameters": [_domain_database(), *refresh_parameters(name)],
            },
            "validation": {"level": "DISPLAYABLE", "isValid": True},
        }
    )
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=response)
    client.get_search_details_with_params = AsyncMock(return_value=response)
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    serve_reads(monkeypatch, response, client)
