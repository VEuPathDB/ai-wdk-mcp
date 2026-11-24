from __future__ import annotations

import httpx
import pytest
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import MultiPickValue, StringValue
from veupathdb.errors import VEuPathDBError
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import (
    VEuPathDBClient,
    WDKSearchResponse,
)

from veupathdb_mcp.catalog import param_dag
from veupathdb_mcp.catalog.search_context import NarrowingUnsupportedError
from veupathdb_mcp.catalog.search_inspection import read_parameter_options

_SEARCH = "GenesByOrthologPattern"
_CONTEXT = {"organism": '["Plasmodium falciparum 3D7"]'}


def _published() -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(
        load_recorded("search_genes_by_ortholog_pattern").json_body()
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

    assert [p.name for p in parameters] == [
        "profile_pattern",
        "included_species",
        "excluded_species",
        "phyletic_indent_map",
        "phyletic_term_map",
        "organism",
    ]


_PAIR = {**_CONTEXT, "profile_pattern": "pfal=1T"}
_NOTE = (
    "not narrowed to your parent values; the site does not narrow organism "
    "with a phyletic pattern"
)


@pytest.mark.usefixtures("refusing_site")
async def test_a_read_under_a_pair_the_site_never_narrows_raises_the_note() -> None:
    fetch = param_dag.wdk_fetch_under_parents_at("plasmodb", "transcript", _SEARCH)

    with pytest.raises(NarrowingUnsupportedError) as raised:
        await fetch(_PAIR)

    assert raised.value.detail == _NOTE


@pytest.mark.usefixtures("refusing_site")
async def test_options_the_site_did_not_narrow_carry_the_mark() -> None:
    info = await read_parameter_options(
        "plasmodb",
        _SEARCH,
        "organism",
        record_type="transcript",
        context_values={"included_species": StringValue(value="x")},
    )

    assert info.kind == "parameter_info"
    assert info.not_narrowed == (
        "not narrowed to your parent values; the site did not answer the read "
        "(HTTP 503)"
    )


@pytest.mark.usefixtures("refusing_site")
async def test_options_under_a_pair_the_site_never_narrows_carry_the_note() -> None:
    info = await read_parameter_options(
        "plasmodb",
        _SEARCH,
        "included_species",
        record_type="transcript",
        context_values={
            "organism": MultiPickValue(values=["Plasmodium falciparum 3D7"]),
            "profile_pattern": StringValue(value="pfal=1T"),
        },
    )

    assert info.kind == "parameter_info"
    assert info.not_narrowed == _NOTE
