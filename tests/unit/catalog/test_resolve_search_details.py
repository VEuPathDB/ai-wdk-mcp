"""The published producer of ``ResolvedSearch``, on a recorded search.

The result says whether WDK built the definition from the caller's values, so
the fallback to the published specs is visible. A search WDK cannot read
raises the catalog's unreadable-search error.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import ParamValue, StringValue
from veupathdb.errors import ValidationError, WDKError
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKRecordType, WDKSearch, WDKSearchResponse

from veupathdb_mcp.catalog import param_validation, resolve_search_details

_RECORDED = "search_genes_by_molecular_weight"
_SEARCH_NAME = "GenesByMolecularWeight"
_RECORD_TYPE = "transcript"
_HINT_RECORD_TYPE = "gene"
_CTX = SearchContext(
    site_id="plasmodb", record_type=_RECORD_TYPE, search_name=_SEARCH_NAME
)
_WEIGHT = "50"
_PARAMETERS: dict[str, ParamValue] = {
    "min_molecular_weight": StringValue(value=_WEIGHT)
}
_CONTEXTUAL_500 = "Internal Error"
_NO_SUCH_SEARCH = "Not found"
_REFUSAL_DETAIL = f"VEuPathDB service error: {_NO_SUCH_SEARCH}"


def _published() -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(load_recorded(_RECORDED).json_body())


class _FakeWDK:
    """The contextual search-details endpoint, answering or refusing."""

    def __init__(self, *, refuses: bool) -> None:
        self._refuses = refuses
        self.contexts: list[dict[str, str]] = []

    async def get_search_details_with_params(
        self,
        record_type: str,
        search_name: str,
        context: dict[str, str] | None = None,
        *,
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        del record_type, search_name, expand_params
        self.contexts.append(dict(context or {}))
        if self._refuses:
            raise WDKError(_CONTEXTUAL_500, status=500)
        return _published()


class _FakeDiscovery:
    """The catalog: the published definition, and the names each record type has."""

    def __init__(self, *, readable: bool) -> None:
        self._readable = readable

    async def get_search_details(
        self, ctx: SearchContext, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del ctx, expand_params
        if not self._readable:
            raise WDKError(_NO_SUCH_SEARCH, status=404)
        return _published()

    async def get_record_types(self, site_id: str) -> list[WDKRecordType]:
        del site_id
        return [
            WDKRecordType(url_segment=_RECORD_TYPE),
            WDKRecordType(url_segment=_HINT_RECORD_TYPE),
        ]

    async def get_searches(self, site_id: str, record_type: str) -> list[WDKSearch]:
        del site_id
        if record_type == _HINT_RECORD_TYPE:
            return [WDKSearch(url_segment=_SEARCH_NAME)]
        return [
            WDKSearch(url_segment="GenesByExonCount"),
            WDKSearch(url_segment="GenesByLocation"),
        ]


def _serve(
    monkeypatch: pytest.MonkeyPatch,
    *,
    readable: bool = True,
    contextual_refuses: bool = False,
) -> _FakeWDK:
    client = _FakeWDK(refuses=contextual_refuses)
    monkeypatch.setattr(param_validation, "get_wdk_client", lambda site_id: client)
    monkeypatch.setattr(
        param_validation,
        "get_discovery_service",
        lambda: _FakeDiscovery(readable=readable),
    )
    return client


async def _resolve() -> param_validation.ResolvedSearch:
    return await resolve_search_details(
        _CTX, resolved_record_type=_RECORD_TYPE, parameters=dict(_PARAMETERS)
    )


class TestTheResultSaysWhetherWdkReadTheValues:
    async def test_the_callers_value_reaches_wdk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _serve(monkeypatch)

        await _resolve()

        assert client.contexts[0]["min_molecular_weight"] == _WEIGHT

    async def test_a_contextual_read_is_reported_as_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve(monkeypatch)

        resolved = await _resolve()

        assert resolved.values_were_read is True
        assert resolved.response.search_data.url_segment == _SEARCH_NAME

    async def test_the_published_specs_answer_a_refused_contextual_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve(monkeypatch, contextual_refuses=True)

        resolved = await _resolve()

        assert resolved.values_were_read is False
        assert resolved.response.search_data.param_names == [
            "organism",
            "min_molecular_weight",
            "max_molecular_weight",
        ]


class TestAnUnreadableSearchRefuses:
    async def test_the_record_types_catalog_is_offered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve(monkeypatch, readable=False)

        with pytest.raises(ValidationError) as excinfo:
            await _resolve()

        assert excinfo.value.title == f"Unknown or invalid search: {_SEARCH_NAME}"
        assert excinfo.value.detail == _REFUSAL_DETAIL
        assert excinfo.value.errors is not None
        entry = cast("dict[str, Any]", excinfo.value.errors[0])
        assert entry["context"] == {
            "recordType": _RECORD_TYPE,
            "availableSearches": ["GenesByExonCount", "GenesByLocation"],
            "recordTypeHint": _HINT_RECORD_TYPE,
        }
