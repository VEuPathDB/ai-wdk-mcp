from __future__ import annotations

import httpx
import pytest
from veupathdb.domain import SearchContext
from veupathdb.domain.strategy import StepValidation
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import (
    VEuPathDBClient,
    WDKSearch,
    WDKSearchResponse,
    WDKStringParam,
)

from veupathdb_mcp.catalog import param_dag

_SEARCH = "GenesByOrthologPattern"
_CONTEXT = {"organism": '["Plasmodium falciparum 3D7"]'}


def _published() -> WDKSearchResponse:
    parameter = WDKStringParam(name="organism", display_name="Organism")
    return WDKSearchResponse(
        search_data=WDKSearch(
            url_segment=_SEARCH, param_names=["organism"], parameters=[parameter]
        ),
        validation=StepValidation(level="NONE", is_valid=False),
    )


class _Discovery:
    async def get_search_details(
        self, ctx: SearchContext, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del ctx, expand_params
        return _published()


def _unavailable(request: httpx.Request) -> httpx.Response:
    if request.method == "GET":
        return httpx.Response(200)
    return httpx.Response(503, text="Service Unavailable")


@pytest.fixture
def refusing_site(monkeypatch: pytest.MonkeyPatch) -> None:
    client = VEuPathDBClient(
        base_url="https://plasmodb.invalid/service",
        site_id="plasmodb",
        transport=httpx.MockTransport(_unavailable),
    )
    monkeypatch.setattr(param_dag, "get_wdk_client", lambda site_id: client)
    monkeypatch.setattr(param_dag, "get_discovery_service", _Discovery)


@pytest.mark.usefixtures("refusing_site")
async def test_a_read_under_parents_raises_the_site_s_refusal() -> None:
    fetch = param_dag.wdk_fetch_under_parents_at("plasmodb", "transcript", _SEARCH)

    with pytest.raises(VEuPathDBError) as raised:
        await fetch(_CONTEXT)

    assert raised.value.status == 503


@pytest.mark.usefixtures("refusing_site")
async def test_the_walk_binds_against_the_published_view() -> None:
    fetch = param_dag.wdk_fetch_at("plasmodb", "transcript", _SEARCH)

    parameters = await fetch(_CONTEXT)

    assert [p.name for p in parameters] == ["organism"]
