"""``fetch_search_details`` raises a ``Search not found`` validation error
whose detail carries did-you-mean suggestions, so the model-facing error
directive (which uses ``str(error)``) can guide self-correction instead of
looping on invented names."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.domain import SearchContext
from veupathdb.errors import ValidationError, VEuPathDBError, VEuPathDBErrorCode

from veupathdb_mcp.catalog import param_discovery


def _search(name: str) -> Any:
    s = MagicMock()
    s.url_segment = name
    return s


@pytest.mark.asyncio
async def test_search_not_found_detail_includes_did_you_mean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery = MagicMock()
    discovery.get_search_details = AsyncMock(
        side_effect=VEuPathDBError(
            code=VEuPathDBErrorCode.WDK_ERROR, title="x", status=404, detail="404"
        )
    )
    discovery.get_searches = AsyncMock(
        return_value=[_search("GenesByText"), _search("GenesByGoTerm")]
    )
    monkeypatch.setattr(param_discovery, "get_discovery_service", lambda: discovery)

    ctx = SearchContext(
        site_id="vectorbase",
        record_type="transcript",
        search_name="GeneByTextSearch",
    )

    with pytest.raises(ValidationError) as excinfo:
        await param_discovery.fetch_search_details(ctx, record_types=[])

    err = excinfo.value
    assert "GenesByText" in err.detail
    assert "GeneByTextSearch" in err.detail


@pytest.mark.asyncio
async def test_a_listed_search_that_cannot_be_read_names_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A search WDK lists but whose definition fails to parse is a read failure.

    Reproduces ``GenesByOrthologPattern`` on plasmodb: the search is in the
    transcript listing, and reading it raised.
    """
    discovery = MagicMock()
    discovery.get_search_details = AsyncMock(
        side_effect=VEuPathDBError(
            code=VEuPathDBErrorCode.DATA_PARSING_ERROR,
            title="Data parsing failed",
            status=502,
            detail="1802 validation errors for WDKSearchResponse",
        )
    )
    discovery.get_searches = AsyncMock(
        return_value=[
            _search("GenesByOrthologPattern"),
            _search("GenesByOrthologs"),
        ]
    )
    monkeypatch.setattr(param_discovery, "get_discovery_service", lambda: discovery)

    ctx = SearchContext(
        site_id="plasmodb",
        record_type="transcript",
        search_name="GenesByOrthologPattern",
    )

    with pytest.raises(VEuPathDBError) as excinfo:
        await param_discovery.fetch_search_details(ctx, record_types=[])

    err = excinfo.value
    assert "Search not found" not in str(err)
    assert "reading GenesByOrthologPattern failed" in err.detail
    assert "1802 validation errors" in err.detail


@pytest.mark.asyncio
async def test_a_read_failure_under_another_record_type_names_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery = MagicMock()
    discovery.get_search_details = AsyncMock(
        side_effect=VEuPathDBError(
            code=VEuPathDBErrorCode.DATA_PARSING_ERROR,
            title="Data parsing failed",
            status=502,
            detail="1802 validation errors",
        )
    )
    discovery.get_searches = AsyncMock(
        return_value=[_search("GenesByText"), _search("GenesByOrthologPattern")]
    )
    monkeypatch.setattr(param_discovery, "get_discovery_service", lambda: discovery)

    rt = MagicMock()
    rt.url_segment = "transcript"
    ctx = SearchContext(
        site_id="plasmodb",
        record_type="organism",
        search_name="GenesByOrthologPattern",
    )

    with pytest.raises(VEuPathDBError) as excinfo:
        await param_discovery.fetch_search_details(ctx, record_types=[rt])

    assert (
        "reading GenesByOrthologPattern failed: Data parsing failed: "
        "1802 validation errors" in excinfo.value.detail
    )


@pytest.mark.asyncio
async def test_an_absent_search_is_never_its_own_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery = MagicMock()
    discovery.get_search_details = AsyncMock(
        side_effect=VEuPathDBError(
            code=VEuPathDBErrorCode.WDK_ERROR, title="x", status=404, detail="404"
        )
    )
    discovery.get_searches = AsyncMock(
        return_value=[_search("GenesByText"), _search("GenesByOrthologs")]
    )
    monkeypatch.setattr(param_discovery, "get_discovery_service", lambda: discovery)

    ctx = SearchContext(
        site_id="plasmodb",
        record_type="transcript",
        search_name="GenesByOrthologPattern",
    )

    with pytest.raises(ValidationError) as excinfo:
        await param_discovery.fetch_search_details(ctx, record_types=[])

    detail = excinfo.value.detail
    assert "Search not found: GenesByOrthologPattern." in detail
    assert "'GenesByOrthologs'" in detail
    assert "'GenesByOrthologPattern'" not in detail


@pytest.mark.asyncio
async def test_a_missing_search_names_the_client_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal rows carry the client library's own code, not the app's."""
    discovery = MagicMock()
    discovery.get_search_details = AsyncMock(
        side_effect=VEuPathDBError(
            code=VEuPathDBErrorCode.WDK_ERROR, title="x", status=404, detail="404"
        )
    )
    discovery.get_searches = AsyncMock(return_value=[_search("GenesByText")])
    monkeypatch.setattr(param_discovery, "get_discovery_service", lambda: discovery)

    ctx = SearchContext(
        site_id="vectorbase",
        record_type="transcript",
        search_name="NoSuchSearch",
    )

    with pytest.raises(ValidationError) as excinfo:
        await param_discovery.fetch_search_details(ctx, record_types=[])

    rows = excinfo.value.errors
    assert rows is not None
    assert rows[0] == {
        "path": "searchName",
        "message": excinfo.value.detail,
        "code": VEuPathDBErrorCode.SEARCH_NOT_FOUND.value,
        "recordType": "transcript",
        "searchName": "NoSuchSearch",
        "availableSearches": ["GenesByText"],
        "details": "x: 404",
    }
