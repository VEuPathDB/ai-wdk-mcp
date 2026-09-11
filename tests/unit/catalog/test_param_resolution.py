"""Reading a search's parameters under a context: what degrades and what raises.

Narrowing is an enrichment. When WDK refuses it, the static view is the answer,
because a search with no parameters is a different claim from one we could not
narrow. A stored value that no longer matches its vocabulary is dropped rather
than failing the read, so the step editor still opens.
"""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import JsonValue
from veupathdb import JSONObject
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    MultiPickValue,
    ParamValue,
    SinglePickValue,
    StringValue,
)
from veupathdb.errors import WDKError
from veupathdb.wdk import WDKEnumParam, WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog import param_resolution
from veupathdb_mcp.catalog.param_resolution import (
    drop_unusable_context_values,
    prefer_original_wdk_error,
)

from .conftest import PHYLETIC_MAPS, hidden_map_param, wdk_search_response

_CTX = SearchContext(
    site_id="plasmodb",
    record_type="transcript",
    search_name="GenesByOrthologPattern",
)
_PARAMS = ("profile_pattern", "organism", *PHYLETIC_MAPS)
_WDK_500 = "Server error '500 Internal Server Error'"
_STRAIN = "Plasmodium falciparum 3D7"


def _vocab_param(name: str) -> WDKParameter:
    raw: JSONObject = {
        "type": "multi-pick-vocabulary",
        "name": name,
        "display_name": name,
        "vocabulary": cast("JsonValue", [[_STRAIN, "P. falciparum 3D7", None]]),
        "allow_empty_value": False,
    }
    return cast("WDKParameter", WDKEnumParam.model_validate(raw))


def _response() -> WDKSearchResponse:
    return wdk_search_response(
        _CTX.search_name,
        [_vocab_param(n) for n in ("profile_pattern", "organism")]
        + [hidden_map_param(n) for n in PHYLETIC_MAPS],
        level="NONE",
        is_valid=False,
    )


class _Client:
    """Answers the static view and refuses to narrow, the way WDK does."""

    def __init__(self, *, contextual_fails: bool) -> None:
        self._contextual_fails = contextual_fails
        self.static_calls = 0
        self.contextual_calls = 0
        self.contexts: list[dict[str, str]] = []

    async def get_search_details(
        self, record_type: str, search_name: str, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del record_type, search_name, expand_params
        self.static_calls += 1
        return _response()

    async def get_search_details_with_params(
        self,
        record_type: str,
        search_name: str,
        context: dict[str, str],
        *,
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        del record_type, search_name, expand_params
        self.contextual_calls += 1
        self.contexts.append(dict(context))
        if self._contextual_fails:
            raise WDKError(_WDK_500, status=500)
        return _response()


def _context() -> dict[str, ParamValue]:
    return {"organism": SinglePickValue(value=_STRAIN)}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    stub = _Client(contextual_fails=True)
    monkeypatch.setattr(param_resolution, "get_wdk_client", lambda site_id: stub)

    async def _record_type(ctx: SearchContext) -> str:
        return ctx.record_type

    async def _discovery(ctx: SearchContext) -> tuple[WDKSearchResponse, set[str]]:
        del ctx
        return _response(), set(_PARAMS)

    monkeypatch.setattr(param_resolution, "find_record_type_for_search", _record_type)
    monkeypatch.setattr(
        param_resolution, "_load_discovery_details_and_allowed", _discovery
    )
    return stub


class TestARefusalToNarrowKeepsTheParameters:
    async def test_the_parameters_still_come_back(self, client: _Client) -> None:
        del client
        response = await param_resolution.expand_search_details_with_params(
            _CTX, _context()
        )

        assert [p.name for p in response.search_data.parameters or []] == list(_PARAMS)

    async def test_the_search_it_answers_for_is_the_one_asked_about(
        self, client: _Client
    ) -> None:
        del client
        response = await param_resolution.expand_search_details_with_params(
            _CTX, _context()
        )

        assert response.search_data.url_segment == _CTX.search_name

    async def test_the_static_view_is_what_answers(self, client: _Client) -> None:
        await param_resolution.expand_search_details_with_params(_CTX, _context())

        assert client.contextual_calls >= 1
        assert client.static_calls == 1


class TestNarrowingIsStillPreferred:
    @pytest.fixture
    def willing(self, monkeypatch: pytest.MonkeyPatch) -> _Client:
        stub = _Client(contextual_fails=False)
        monkeypatch.setattr(param_resolution, "get_wdk_client", lambda site_id: stub)
        return stub

    async def test_the_static_view_is_not_asked_for_when_wdk_narrows(
        self, client: _Client, willing: _Client
    ) -> None:
        del client
        await param_resolution.expand_search_details_with_params(_CTX, _context())

        assert willing.contextual_calls == 1
        assert willing.static_calls == 0

    async def test_the_hidden_structural_params_are_sent(
        self, client: _Client, willing: _Client
    ) -> None:
        del client
        # WDK answers 500 to a phyletic read whose context omits either map.
        await param_resolution.expand_search_details_with_params(_CTX, _context())

        assert willing.contexts[0] == {
            "organism": f'["{_STRAIN}"]',
            "phyletic_indent_map": "[]",
            "phyletic_term_map": "[]",
        }


class TestDropUnusableContextValues:
    """One saved value that no longer matches its vocabulary must not make the
    step editor impossible to open. Mutations keep validating strictly."""

    def test_it_keeps_values_that_canonicalize(self) -> None:
        context: dict[str, ParamValue] = {"organism": MultiPickValue(values=[_STRAIN])}

        def canonicalize(values: dict[str, ParamValue]) -> dict[str, ParamValue]:
            return values

        assert drop_unusable_context_values(context, canonicalize) == context

    def test_it_drops_only_the_offending_value(self) -> None:
        good = MultiPickValue(values=[_STRAIN])
        bad = MultiPickValue(values=["[]"])
        context: dict[str, ParamValue] = {"organism": good, "phyletic_term_map": bad}

        def canonicalize(values: dict[str, ParamValue]) -> dict[str, ParamValue]:
            if "phyletic_term_map" in values:
                msg = "Parameter 'phyletic_term_map' does not accept '[]'."
                raise ValueError(msg)
            return values

        assert drop_unusable_context_values(context, canonicalize) == {"organism": good}

    def test_it_returns_empty_when_every_value_is_unusable(self) -> None:
        context: dict[str, ParamValue] = {
            "a": StringValue(value="x"),
            "b": StringValue(value="y"),
        }

        def canonicalize(values: dict[str, ParamValue]) -> dict[str, ParamValue]:
            if values:
                msg = "all bad"
                raise ValueError(msg)
            return values

        assert drop_unusable_context_values(context, canonicalize) == {}

    def test_an_empty_context_is_returned_unchanged(self) -> None:
        def canonicalize(values: dict[str, ParamValue]) -> dict[str, ParamValue]:
            return values

        assert drop_unusable_context_values({}, canonicalize) == {}


class TestPreferOriginalWdkError:
    """A component-site search that fails and then fails again on the portal must
    report the site's diagnosis, not the portal's 500."""

    def test_the_portal_message_does_not_replace_the_site_one(self) -> None:
        chosen = prefer_original_wdk_error(
            WDKError("GenesByOrthologPattern rejected phyletic_indent_map", 422),
            WDKError("Internal Server Error", 500),
        )

        assert str(chosen.detail).startswith("GenesByOrthologPattern rejected")

    def test_the_original_message_survives(self) -> None:
        chosen = prefer_original_wdk_error(
            WDKError("phyletic_indent_map does not accept '[]'", 422),
            WDKError("Internal Server Error", 500),
        )

        assert "phyletic_indent_map" in str(chosen.detail)

    def test_the_fallback_failure_is_still_recorded(self) -> None:
        """Dropping it entirely would hide that a second call was even made."""
        chosen = prefer_original_wdk_error(
            WDKError("original failure", 422), WDKError("portal exploded", 500)
        )

        assert "portal exploded" in str(chosen.detail)

    def test_the_original_status_is_kept(self) -> None:
        """A 422 from the site is a different problem from a portal 500 and must
        not be reported as one."""
        chosen = prefer_original_wdk_error(
            WDKError("bad parameter", 422), WDKError("Internal Server Error", 500)
        )

        assert chosen.status == 422

    def test_it_stays_a_wdk_error(self) -> None:
        chosen = prefer_original_wdk_error(WDKError("a", 422), WDKError("b", 500))

        assert type(chosen) is WDKError
