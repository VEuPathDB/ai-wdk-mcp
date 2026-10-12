"""A gene lookup is a keyed WDK read, so it travels with the researcher's token alone."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.errors import WDKLoginRequiredError

from veupathdb_mcp.gene_lookup import resolve_gene_ids

RESEARCHER_TOKEN = "researcher.registered.token"


def _answer(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/app"):
        return httpx.Response(200, text="ok")
    if path.endswith("/users/current"):
        return httpx.Response(200, json={"id": 42, "isGuest": False})
    if path.endswith("/datasets"):
        return httpx.Response(200, json={"id": 7})
    return httpx.Response(
        200, json={"meta": {"totalCount": 0, "responseCount": 0}, "records": []}
    )


@pytest.fixture
def deployment_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEUPATHDB_AUTH_TOKEN", "deployment.account.token")


@pytest.fixture
def researcher() -> Iterator[None]:
    reset = veupathdb_auth_token_ctx.set(RESEARCHER_TOKEN)
    try:
        yield
    finally:
        veupathdb_auth_token_ctx.reset(reset)


@pytest.mark.usefixtures("deployment_environment")
@respx.mock
async def test_a_lookup_with_no_researcher_token_is_refused_before_a_request() -> None:
    route = respx.route().mock(side_effect=_answer)
    reset = veupathdb_auth_token_ctx.set(None)
    try:
        with pytest.raises(WDKLoginRequiredError):
            await resolve_gene_ids("plasmodb", ["PF3D7_1133400"])
    finally:
        veupathdb_auth_token_ctx.reset(reset)

    assert not route.called


@pytest.mark.usefixtures("deployment_environment", "researcher")
@respx.mock
async def test_every_lookup_request_carries_the_researcher_token() -> None:
    route = respx.route().mock(side_effect=_answer)

    result = await resolve_gene_ids("plasmodb", ["PF3D7_1133400"])

    assert result.error is None
    assert {call.request.url.path.rsplit("/", 1)[-1] for call in route.calls} >= {
        "datasets",
        "standard",
    }
    assert {call.request.headers["cookie"] for call in route.calls} == {
        f"Authorization={RESEARCHER_TOKEN}"
    }
