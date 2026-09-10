"""The verdict the strategy editor blocks a save on.

The route relays WDK's own bundle. A definition WDK built without the editor's
values judged a different shape, so it casts no verdict and the save proceeds
to the push that does.
"""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import JsonValue
from veupathdb.domain.parameters.values import MultiPickValue, ParamValue, StringValue
from veupathdb.domain.search import SearchContext
from veupathdb.errors import (
    ValidationError,
    WDKError,
    param_message_rows,
)
from veupathdb.json_types import JSONObject
from veupathdb.wdk.wdk_models import WDKSearchResponse
from veupathdb.wdk.wdk_parameters import (
    WDKEnumParam,
    WDKParameter,
    WDKStringParam,
)

from veupathdb_mcp.catalog import param_validation

from .conftest import wdk_search_response

_NO_SUCH_SEARCH = "no such search"
_CTX = SearchContext(
    site_id="plasmodb", record_type="transcript", search_name="GenesByEcNumber"
)
_EMPTY = "Cannot be empty."
_ORGANISM = "Plasmodium falciparum 3D7"


_NO_SUCH_SEARCH = "no such search"


def _organism() -> WDKParameter:
    raw: JSONObject = {
        "type": "multi-pick-vocabulary",
        "name": "organism",
        "display_name": "Organism",
        "display_type": "treeBox",
        "allow_empty_value": False,
        "vocabulary": cast("JsonValue", [[_ORGANISM, _ORGANISM, None]]),
    }
    return cast("WDKParameter", WDKEnumParam.model_validate(raw))


def _params() -> list[WDKParameter]:
    return [
        _organism(),
        WDKStringParam(
            name="ec_wildcard", display_name="ec_wildcard", allow_empty_value=False
        ),
    ]


def _response(
    *, level: str = "SEMANTIC", is_valid: bool = True, errors: JSONObject | None = None
) -> WDKSearchResponse:
    return wdk_search_response(
        _CTX.search_name, _params(), level=level, is_valid=is_valid, errors=errors
    )


def _serve(
    monkeypatch: pytest.MonkeyPatch,
    response: WDKSearchResponse,
    *,
    values_were_read: bool = True,
) -> None:
    async def _details(
        ctx: SearchContext,
        *,
        resolved_record_type: str,
        parameters: dict[str, ParamValue],
    ) -> param_validation.ResolvedSearch:
        del ctx, resolved_record_type, parameters
        return param_validation.ResolvedSearch(
            response=response, values_were_read=values_were_read
        )

    monkeypatch.setattr(param_validation, "resolve_search_details", _details)


async def _validate(
    values: dict[str, ParamValue] | None = None,
) -> param_validation.ValidationResponse:
    return await param_validation.validate_search_params(
        _CTX,
        context_values=(
            {"organism": MultiPickValue(values=[_ORGANISM])}
            if values is None
            else values
        ),
    )


_REJECTED: JSONObject = {"general": [], "byKey": {"ec_wildcard": [_EMPTY]}}


class TestWdksVerdictBlocksTheSave:
    async def test_the_save_is_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _serve(monkeypatch, _response(is_valid=False, errors=_REJECTED))

        assert (await _validate()).validation.is_valid is False

    async def test_the_per_parameter_messages_are_relayed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve(monkeypatch, _response(is_valid=False, errors=_REJECTED))

        errors = (await _validate()).validation.errors

        assert errors.by_key == {"ec_wildcard": [_EMPTY]}
        assert errors.general == []

    async def test_the_canonical_values_still_come_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve(monkeypatch, _response(is_valid=False, errors=_REJECTED))

        result = await _validate()

        assert result.validation.normalized_context_values == {"organism": [_ORGANISM]}


class TestNoVerdictDoesNotBlockTheSave:
    async def test_an_unchecked_bundle_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Level NONE reports invalid with no errors and means nobody looked.
        _serve(monkeypatch, _response(level="NONE", is_valid=False))

        assert (await _validate()).validation.is_valid is True

    async def test_a_fallback_definition_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve(
            monkeypatch,
            _response(is_valid=False, errors=_REJECTED),
            values_were_read=False,
        )

        assert (await _validate()).validation.is_valid is True


class TestAValueTheCanonicalizerRefuses:
    async def test_a_name_the_search_does_not_have_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The editor primes the form from the step it opened, so a key the
        # search has since stopped publishing is left out rather than refused.
        _serve(monkeypatch, _response())

        result = await _validate(
            {
                "organism": MultiPickValue(values=[_ORGANISM]),
                "made_up": StringValue(value="x"),
            }
        )

        assert result.validation.is_valid is True
        assert result.validation.normalized_context_values == {"organism": [_ORGANISM]}

    async def test_a_value_outside_the_vocabulary_names_the_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _serve(monkeypatch, _response())

        result = await _validate({"organism": MultiPickValue(values=["Not a strain"])})

        assert list(result.validation.errors.by_key) == ["organism"]


class TestTheRefusalProjection:
    """Every row of a refusal reaches the editor, whatever shape it holds."""

    def test_a_row_of_messages_lands_under_its_parameter(self) -> None:
        errors = param_validation._refusal_errors(
            ValidationError(
                title="profile_pattern is not a census pattern",
                detail="'prose' is not built from census tokens. Call it.",
                errors=param_message_rows(
                    {"profile_pattern": ["'prose' is not built from census tokens."]}
                ),
            )
        )

        assert errors.by_key == {
            "profile_pattern": ["'prose' is not built from census tokens."]
        }
        assert errors.general == ["'prose' is not built from census tokens. Call it."]

    def test_a_row_that_is_not_an_object_is_reported_as_general(self) -> None:
        errors = param_validation._refusal_errors(
            ValidationError(title="Refused", detail="d", errors=["organism is bad"])
        )

        assert errors.by_key == {}
        assert errors.general == ["organism is bad"]

    def test_a_row_naming_no_parameter_falls_back_to_the_detail(self) -> None:
        errors = param_validation._refusal_errors(
            ValidationError(title="Refused", detail="d", errors=[{"context": {}}])
        )

        assert errors.by_key == {}
        assert errors.general == ["d"]


class TestAnUnreadableSearch:
    async def test_the_failure_is_reported_as_general(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _raise(
            ctx: SearchContext,
            *,
            resolved_record_type: str,
            parameters: dict[str, ParamValue],
        ) -> param_validation.ResolvedSearch:
            del ctx, resolved_record_type, parameters
            raise WDKError(_NO_SUCH_SEARCH, status=404)

        monkeypatch.setattr(param_validation, "resolve_search_details", _raise)
        result = await _validate()

        assert result.validation.is_valid is False
        assert result.validation.errors.general == [
            f"Failed to load search metadata: VEuPathDB service error: {_NO_SUCH_SEARCH}"
        ]


class TestAValidRead:
    async def test_the_save_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _serve(monkeypatch, _response())
        result = await _validate()

        assert result.validation.is_valid is True
        assert result.validation.errors.by_key == {}
