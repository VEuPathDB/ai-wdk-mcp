"""The contextual read, the static fallback, and what each may call substituted.

``GenesByOrthologPattern`` answers 500 to a contextual read whose context omits
either structural map, so a read that reaches WDK proves they are sent. When the
read fails, WDK renders the static definition, whose echoed values are the
published defaults and never a verdict on the caller.
"""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters.values import (
    MultiPickValue,
    ParamValue,
    StringValue,
)
from veupathdb.domain.search import SearchContext
from veupathdb.errors import ValidationError, WDKError
from veupathdb.wdk.wdk_models import WDKSearchResponse

from veupathdb_mcp.catalog import param_validation

from .conftest import (
    PHYLETIC_MAPS,
    PHYLETIC_STRAIN,
    no_dependent_refresh,
    phyletic_search_params,
    validation_callbacks,
    wdk_search_response,
)

_CTX = SearchContext(
    site_id="plasmodb",
    record_type="transcript",
    search_name="GenesByOrthologPattern",
)
_PATTERN = "%hsap:N%pfal:Y%"
_WDK_500 = "Internal Error"
_STATED: dict[str, ParamValue] = {
    "profile_pattern": StringValue(value=_PATTERN),
    "included_species": StringValue(value="pfal"),
    "excluded_species": StringValue(value="hsap"),
    "organism": MultiPickValue(values=[PHYLETIC_STRAIN]),
}


def _definition(*, pattern: str = "hsap=1T", organism: str = "[]") -> WDKSearchResponse:
    return wdk_search_response(
        _CTX.search_name,
        phyletic_search_params(pattern=pattern, organism_initial=organism),
    )


def _rejecting_definition() -> WDKSearchResponse:
    return wdk_search_response(
        _CTX.search_name,
        phyletic_search_params(),
        level="DISPLAYABLE",
        is_valid=False,
        errors={"general": [], "byKey": {"organism": ["Cannot be empty."]}},
    )


async def _validate() -> param_validation.ValidatedParams:
    return await param_validation.validate_parameters(
        _CTX, parameters=dict(_STATED), callbacks=validation_callbacks()
    )


async def _resolve() -> param_validation.ResolvedSearch:
    return await param_validation.resolve_search_details(
        _CTX,
        resolved_record_type="transcript",
        parameters={
            "profile_pattern": StringValue(value=_PATTERN),
            "organism": MultiPickValue(values=[PHYLETIC_STRAIN]),
        },
    )


class _FakeWDK:
    """Answers the search-details endpoints the way live PlasmoDB does."""

    def __init__(self) -> None:
        self.contexts: list[dict[str, str]] = []

    async def get_search_details(
        self, record_type: str, search_name: str, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del record_type, search_name, expand_params
        # The published definition: the caller's values are absent.
        return _definition()

    async def get_search_details_with_params(
        self,
        record_type: str,
        search_name: str,
        context: dict[str, str] | None = None,
        *,
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        del record_type, search_name, expand_params
        sent = context or {}
        self.contexts.append(dict(sent))
        if any(name not in sent for name in PHYLETIC_MAPS):
            raise WDKError(_WDK_500, status=500)
        return _definition(
            pattern=sent.get("profile_pattern", "hsap=1T"),
            organism=sent.get("organism", "[]"),
        )


class _FakeDiscovery:
    def __init__(self, response: WDKSearchResponse) -> None:
        self._response = response

    async def get_search_details(
        self, ctx: SearchContext, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del ctx, expand_params
        return self._response


@pytest.fixture
def fake_wdk(monkeypatch: pytest.MonkeyPatch) -> _FakeWDK:
    client = _FakeWDK()
    monkeypatch.setattr(param_validation, "get_wdk_client", lambda site_id: client)
    monkeypatch.setattr(
        param_validation, "get_discovery_service", lambda: _FakeDiscovery(_definition())
    )
    monkeypatch.setattr(
        param_validation, "get_refreshed_dependent_params", no_dependent_refresh
    )
    return client


class TestTheContextualReadHappens:
    async def test_wdk_read_the_callers_values(self, fake_wdk: _FakeWDK) -> None:
        del fake_wdk

        assert (await _resolve()).values_were_read is True

    async def test_the_structural_maps_are_sent(self, fake_wdk: _FakeWDK) -> None:
        await _validate()

        assert fake_wdk.contexts
        for context in fake_wdk.contexts:
            assert context["phyletic_indent_map"] == "[]"
            assert context["phyletic_term_map"] == "[]"

    async def test_the_callers_values_reach_wdk(self, fake_wdk: _FakeWDK) -> None:
        await _validate()

        assert fake_wdk.contexts[0]["profile_pattern"] == _PATTERN
        assert fake_wdk.contexts[0]["organism"] == f'["{PHYLETIC_STRAIN}"]'

    async def test_nothing_is_reported_as_substituted(self, fake_wdk: _FakeWDK) -> None:
        del fake_wdk

        assert (await _validate()).substituted == []

    async def test_the_stated_values_survive(self, fake_wdk: _FakeWDK) -> None:
        del fake_wdk
        result = await _validate()

        assert result.params["profile_pattern"] == StringValue(value=_PATTERN)
        assert result.params["organism"] == MultiPickValue(values=[PHYLETIC_STRAIN])


class TestAGenuine500StillFallsBack:
    async def test_the_static_definition_answers(
        self, fake_wdk: _FakeWDK, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _always_500(
            record_type: str,
            search_name: str,
            context: dict[str, str] | None = None,
            *,
            expand_params: bool = True,
        ) -> WDKSearchResponse:
            del record_type, search_name, context, expand_params
            raise WDKError(_WDK_500, status=500)

        monkeypatch.setattr(fake_wdk, "get_search_details_with_params", _always_500)

        resolved = await _resolve()
        result = await _validate()

        assert resolved.values_were_read is False
        assert result.params["organism"] == MultiPickValue(values=[PHYLETIC_STRAIN])


@pytest.fixture
def static_wdk(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _static(
        ctx: SearchContext,
        *,
        resolved_record_type: str,
        parameters: dict[str, ParamValue],
    ) -> param_validation.ResolvedSearch:
        del ctx, resolved_record_type, parameters
        return param_validation.ResolvedSearch(
            response=_definition(), values_were_read=False
        )

    monkeypatch.setattr(param_validation, "resolve_search_details", _static)
    monkeypatch.setattr(
        param_validation, "get_refreshed_dependent_params", no_dependent_refresh
    )


class TestNothingTheCallerStatedIsADefault:
    async def test_a_derived_hidden_value_is_not_reported(
        self, static_wdk: None
    ) -> None:
        del static_wdk

        assert "profile_pattern" not in (await _validate()).substituted

    async def test_a_stated_organism_is_not_reported(self, static_wdk: None) -> None:
        del static_wdk

        assert "organism" not in (await _validate()).substituted

    async def test_a_structural_map_is_not_reported(self, static_wdk: None) -> None:
        del static_wdk
        # The two maps allow empty and carry the empty selection, so nothing was
        # filled and nothing was substituted.

        assert (await _validate()).substituted == []

    async def test_the_stated_values_survive(self, static_wdk: None) -> None:
        del static_wdk
        result = await _validate()

        assert result.params["profile_pattern"] == StringValue(value=_PATTERN)
        assert result.params["organism"] == MultiPickValue(values=[PHYLETIC_STRAIN])


class _FailingContextualClient:
    """A WDK client whose contextual read answers 500."""

    async def get_search_details_with_params(
        self,
        record_type: str,
        search_name: str,
        *,
        context: dict[str, str],
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        del record_type, search_name, context, expand_params
        raise WDKError(_WDK_500, status=500)


class TestAFallbackDefinitionCastsNoVerdict:
    """WDK judged no caller when the contextual read failed.

    The published definition carries the verdict on the empty parameter shape,
    which rejects every required parameter the caller in fact supplied.
    """

    @pytest.fixture(autouse=True)
    def _published_rejection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            param_validation,
            "get_wdk_client",
            lambda site_id: _FailingContextualClient(),
        )
        monkeypatch.setattr(
            param_validation,
            "get_discovery_service",
            lambda: _FakeDiscovery(_rejecting_definition()),
        )
        monkeypatch.setattr(
            param_validation, "get_refreshed_dependent_params", no_dependent_refresh
        )

    async def test_a_rejection_in_the_fallback_does_not_raise(self) -> None:
        result = await _validate()

        assert result.params["organism"] == MultiPickValue(values=[PHYLETIC_STRAIN])

    async def test_a_contextual_rejection_still_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _reject(
            ctx: SearchContext,
            *,
            resolved_record_type: str,
            parameters: dict[str, ParamValue],
        ) -> param_validation.ResolvedSearch:
            del ctx, resolved_record_type, parameters
            return param_validation.ResolvedSearch(
                response=_rejecting_definition(), values_were_read=True
            )

        monkeypatch.setattr(param_validation, "resolve_search_details", _reject)

        with pytest.raises(ValidationError, match="Invalid parameter value"):
            await _validate()
