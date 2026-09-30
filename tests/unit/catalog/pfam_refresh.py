"""Two recorded Pfam vocabularies of ``GenesByInterproDomain``, served by a stub client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import search_inspection, searches

FIXTURES = Path(__file__).parent / "fixtures"
DAL972 = "tritrypdb_dal972_pfam_refresh"
FOWLERI = "amoebadb_nfowleri_pfam_refresh"
SEARCH = "GenesByInterproDomain"
PARAMETER = "domain_typeahead"
CONTEXT = {"domain_database": "Pfam"}


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
                "parameters": refresh_parameters(name),
            },
            "validation": {"level": "DISPLAYABLE", "isValid": True},
        }
    )
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=response)
    client.get_search_details_with_params = AsyncMock(return_value=response)
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda _site: client)
