"""The census-pattern guards refuse at pre-flight, not one push later.

WDK validates ``profile_pattern`` as a string of a length and nothing else, so a
pattern in prose, a pattern naming a code the census does not hold, and a pattern
stating one code twice are all answered with a step id and a valid verdict. The
faults have to be found before the criterion is accepted, or the model learns
about them from a later tool call.
"""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import JsonValue
from veupathdb.domain.parameters.values import MultiPickValue, ParamValue, StringValue
from veupathdb.domain.search import SearchContext
from veupathdb.errors import ValidationError
from veupathdb.json_types import JSONObject
from veupathdb.wdk.wdk_parameters import (
    WDKEnumParam,
    WDKParameter,
    WDKStringParam,
)

from veupathdb_mcp.catalog import param_validation

from .conftest import (
    PHYLETIC_STRAIN,
    no_dependent_refresh,
    organism_param,
    validation_callbacks,
    wdk_search_response,
)

_CTX = SearchContext(
    site_id="plasmodb", record_type="transcript", search_name="GenesByOrthologPattern"
)
# Live on plasmodb.org 2026-09-04: this value was answered 200, stored, and
# reported valid at RUNNABLE.
_PROSE = "Plasmodium falciparum AND NOT Homo sapiens"
_CENSUS = "%hsap:N%pfal:Y%"
_TERMS = [["hsap", "Homo sapiens", None], ["pfal", "Plasmodium falciparum", None]]
_INDENTS = [["hsap", "1", None], ["pfal", "1", None]]


def _map_param(name: str, entries: list[list[str | None]] | None) -> WDKParameter:
    raw: JSONObject = {
        "type": "multi-pick-vocabulary",
        "name": name,
        "display_name": name,
        "display_type": "checkBox",
        "is_visible": False,
        "allow_empty_value": True,
        "initial_display_value": "[]",
        "vocabulary": cast("JsonValue", entries),
    }
    return cast("WDKParameter", WDKEnumParam.model_validate(raw))


def _phyletic_params(*, readable_tree: bool) -> list[WDKParameter]:
    return [
        WDKStringParam(
            name="profile_pattern",
            display_name="profile_pattern",
            is_visible=False,
            allow_empty_value=False,
            initial_display_value="hsap=1T",
        ),
        *(
            WDKStringParam(
                name=name,
                display_name=name,
                allow_empty_value=True,
                initial_display_value="",
            )
            for name in ("included_species", "excluded_species")
        ),
        _map_param("phyletic_term_map", _TERMS if readable_tree else None),
        _map_param("phyletic_indent_map", _INDENTS if readable_tree else None),
        organism_param("[]"),
    ]


@pytest.fixture
def readable_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, readable_tree=True)


@pytest.fixture
def unreadable_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, readable_tree=False)


def _serve(monkeypatch: pytest.MonkeyPatch, *, readable_tree: bool) -> None:
    response = wdk_search_response(
        _CTX.search_name, _phyletic_params(readable_tree=readable_tree)
    )

    async def _details(
        ctx: SearchContext,
        *,
        resolved_record_type: str,
        parameters: dict[str, ParamValue],
    ) -> param_validation.ResolvedSearch:
        del ctx, resolved_record_type, parameters
        return param_validation.ResolvedSearch(response=response, values_were_read=True)

    monkeypatch.setattr(param_validation, "_resolve_search_details", _details)
    monkeypatch.setattr(
        param_validation, "get_refreshed_dependent_params", no_dependent_refresh
    )


async def _validate(pattern: str) -> param_validation.ValidatedParams:
    return await param_validation.validate_parameters(
        _CTX,
        parameters={
            "profile_pattern": StringValue(value=pattern),
            "organism": MultiPickValue(values=[PHYLETIC_STRAIN]),
        },
        callbacks=validation_callbacks(),
    )


class TestAProsePatternIsRefusedBeforeThePush:
    async def test_the_criterion_is_refused(self, readable_tree: None) -> None:
        del readable_tree

        with pytest.raises(ValidationError, match="not a census pattern"):
            await _validate(_PROSE)

    async def test_the_refusal_quotes_the_census_form(
        self, readable_tree: None
    ) -> None:
        del readable_tree
        with pytest.raises(ValidationError) as excinfo:
            await _validate(_PROSE)

        assert "%code:Y%" in (excinfo.value.detail or "")

    async def test_the_refusal_names_the_lookup_tool(self, readable_tree: None) -> None:
        del readable_tree
        with pytest.raises(ValidationError) as excinfo:
            await _validate(_PROSE)

        assert "lookup_phyletic_codes" in (excinfo.value.detail or "")


class TestAnUnknownCodeIsRefusedBeforeThePush:
    async def test_the_criterion_is_refused(self, readable_tree: None) -> None:
        del readable_tree

        with pytest.raises(ValidationError, match="Unknown codes: zzzz"):
            await _validate("%zzzz:Y%")

    async def test_only_the_unknown_code_is_listed(self, readable_tree: None) -> None:
        del readable_tree
        with pytest.raises(ValidationError) as excinfo:
            await _validate("%hsap:Y%zzzz:Y%")

        assert "Unknown codes: zzzz." in (excinfo.value.detail or "")


class TestARepeatedCodeIsRefusedBeforeThePush:
    async def test_the_criterion_is_refused(self, readable_tree: None) -> None:
        del readable_tree

        with pytest.raises(ValidationError, match="states one code twice"):
            await _validate("%hsap:Y%hsap:N%")


class TestACensusPatternPasses:
    async def test_the_stated_pattern_survives(self, readable_tree: None) -> None:
        del readable_tree

        assert (await _validate(_CENSUS)).params["profile_pattern"] == StringValue(
            value=_CENSUS
        )

    async def test_the_bare_wildcard_states_no_constraint(
        self, readable_tree: None
    ) -> None:
        del readable_tree

        assert (await _validate("%")).params["profile_pattern"] == StringValue(
            value="%"
        )


class TestAnUnreadableTreeJudgesOnlyTheShape:
    async def test_the_shape_is_still_refused(self, unreadable_tree: None) -> None:
        del unreadable_tree

        with pytest.raises(ValidationError, match="not a census pattern"):
            await _validate(_PROSE)

    async def test_an_unknown_code_passes_because_nothing_can_judge_it(
        self, unreadable_tree: None
    ) -> None:
        del unreadable_tree

        assert (await _validate("%zzzz:Y%")).params["profile_pattern"] == StringValue(
            value="%zzzz:Y%"
        )


class TestOnlyAPhyleticSearchIsJudged:
    """The grammar belongs to the search that carries the whole parameter set.

    A search holding the name and not the census maps states a different
    criterion, and refusing its value would refuse a legal one.
    """

    async def test_a_search_without_the_maps_keeps_its_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = wdk_search_response(
            "GenesByProfilePattern",
            [
                WDKStringParam(
                    name="profile_pattern",
                    display_name="profile_pattern",
                    allow_empty_value=False,
                ),
                organism_param("[]"),
            ],
        )

        async def _details(
            ctx: SearchContext,
            *,
            resolved_record_type: str,
            parameters: dict[str, ParamValue],
        ) -> param_validation.ResolvedSearch:
            del ctx, resolved_record_type, parameters
            return param_validation.ResolvedSearch(
                response=response, values_were_read=True
            )

        monkeypatch.setattr(param_validation, "_resolve_search_details", _details)
        monkeypatch.setattr(
            param_validation, "get_refreshed_dependent_params", no_dependent_refresh
        )

        result = await param_validation.validate_parameters(
            SearchContext("plasmodb", "transcript", "GenesByProfilePattern"),
            parameters={
                "profile_pattern": StringValue(value=_PROSE),
                "organism": MultiPickValue(values=[PHYLETIC_STRAIN]),
            },
            callbacks=validation_callbacks(),
        )

        assert result.params["profile_pattern"] == StringValue(value=_PROSE)
