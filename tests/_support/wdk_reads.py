"""The parameter reads of one search, answered from one recorded response."""

from __future__ import annotations

import pytest
from veupathdb.domain import SearchContext
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import param_dag


class _Answering:
    def __init__(self, response: WDKSearchResponse) -> None:
        self._response = response

    async def get_search_details_with_params(
        self, *args: object, **kwargs: object
    ) -> WDKSearchResponse:
        del args, kwargs
        return self._response


def serve_reads(
    monkeypatch: pytest.MonkeyPatch,
    response: WDKSearchResponse,
    client: object | None = None,
) -> None:
    """Answer the published read and every read under a context with ``response``,
    or the contextual reads with ``client`` when one is given."""

    class _Catalog:
        async def get_search_details(
            self, ctx: SearchContext, *, expand_params: bool = True
        ) -> WDKSearchResponse:
            del ctx, expand_params
            return response

    answering = client or _Answering(response)
    monkeypatch.setattr(param_dag, "get_discovery_service", _Catalog)
    monkeypatch.setattr(param_dag, "get_wdk_client", lambda site_id: answering)
