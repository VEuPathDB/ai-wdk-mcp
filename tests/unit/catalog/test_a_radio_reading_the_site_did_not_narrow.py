from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests._support.wdk_reads import serve_reads
from veupathdb.errors import VEuPathDBError, VEuPathDBErrorCode
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import search_inspection, searches
from veupathdb_mcp.catalog.search_context import NarrowingUnsupported
from veupathdb_mcp.catalog.search_inspection import read_radio_readings

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "plasmodb_3d7_interpro_vocabulary_half_off.json"
)
_SEARCH = "GenesByInterproDomain"
_CONTEXT = {"organism": ["Plasmodium falciparum 3D7"], "domain_database": "INTERPRO"}
_NOTE = "not narrowed to your parent values; the site does not narrow these values"


def _recorded() -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(
        json.loads(_FIXTURE.read_text())["response_json"]
    )


def _serve(monkeypatch: pytest.MonkeyPatch, narrowed: AsyncMock) -> None:
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=_recorded())
    client.get_search_details_with_params = narrowed
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda _site: client)
    serve_reads(monkeypatch, _recorded(), client)


async def _read() -> list[search_inspection.RadioReadings]:
    return await read_radio_readings(
        "plasmodb",
        _SEARCH,
        "protein kinase",
        about=None,
        record_type="transcript",
        context_values=_CONTEXT,
    )


async def test_a_narrowed_reading_carries_no_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, AsyncMock(return_value=_recorded()))

    (reading,) = await _read()

    assert reading.not_narrowed is None


async def test_a_reading_the_site_did_not_answer_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = VEuPathDBError(
        code=VEuPathDBErrorCode.WDK_ERROR,
        title="Service Unavailable",
        status=503,
        detail="503",
    )
    _serve(monkeypatch, AsyncMock(side_effect=refusal))

    with pytest.raises(VEuPathDBError) as raised:
        await _read()

    assert raised.value.status == 503


async def test_a_reading_under_a_context_the_site_never_narrows_carries_the_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, AsyncMock(return_value=_recorded()))

    async def unsupported(*args: object, **kwargs: object) -> NarrowingUnsupported:
        del args, kwargs
        return NarrowingUnsupported(published=_recorded(), note=_NOTE)

    monkeypatch.setattr(
        search_inspection, "get_search_params_under_context", unsupported
    )

    (reading,) = await _read()

    assert reading.not_narrowed == _NOTE
    assert reading.label is not None
