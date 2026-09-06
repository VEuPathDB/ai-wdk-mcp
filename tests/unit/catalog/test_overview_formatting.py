"""The search overview carries each parameter's values, not a count of them."""

from __future__ import annotations

from veupathdb.wdk.wdk_models import WDKSearch
from veupathdb.wdk.wdk_parameters import (
    WDKEnumParam,
    WDKNumberParam,
    WDKParameter,
    WDKStringParam,
)

from veupathdb_mcp.catalog.overview_formatting import (
    SearchOverviewResult,
    format_search_overview,
)
from veupathdb_mcp.catalog.param_formatting import format_param_info_typed


def _vocab(*terms: str) -> list[tuple[str, str, None]]:
    return [(t, t.upper(), None) for t in terms]


def _overview(params: list[WDKParameter]) -> SearchOverviewResult:
    return format_search_overview(
        definition=WDKSearch(
            url_segment="GenesByGoTerm",
            display_name="Genes by GO Term",
            description="Find genes by GO term",
            param_names=[p.name for p in params],
        ),
        record_type="transcript",
        infos=format_param_info_typed(params),
        query="kinase genes",
    )


def test_a_vocabulary_travels_with_the_overview() -> None:
    param = WDKEnumParam.model_validate(
        {
            "name": "go_term",
            "type": "single-pick-vocabulary",
            "displayName": "GO term",
            "allowEmptyValue": False,
            "vocabulary": _vocab("kinase", "phosphatase"),
        }
    )

    overview = _overview([param])

    [entry] = overview.required
    assert [o.value for o in entry.vocabulary] == ["kinase", "phosphatase"]
    assert entry.vocabulary_total == 2
    assert entry.vocabulary_note is None


def test_optional_params_are_split_out_and_keep_their_bounds() -> None:
    required = WDKStringParam.model_validate({"name": "text", "allowEmptyValue": False})
    optional = WDKNumberParam.model_validate(
        {"name": "evalue", "allowEmptyValue": True, "min": 0.0, "max": 1.0}
    )

    overview = _overview([required, optional])

    assert [p.name for p in overview.required] == ["text"]
    [entry] = overview.optional
    assert entry.name == "evalue"
    assert entry.min == 0.0
    assert entry.max == 1.0


def test_a_dependent_param_is_listed_under_dependencies() -> None:
    parent = WDKEnumParam.model_validate(
        {
            "name": "organism",
            "type": "single-pick-vocabulary",
            "dependentParams": ["strain"],
            "vocabulary": _vocab("pfal"),
        }
    )
    child = WDKEnumParam.model_validate(
        {
            "name": "strain",
            "type": "single-pick-vocabulary",
            "vocabulary": _vocab("3D7"),
        }
    )

    overview = _overview([parent, child])

    assert overview.dependencies["strain"].depends_on == ["organism"]
    [entry] = [p for p in overview.required if p.name == "organism"]
    assert entry.controls_vocab_of == ["strain"]


def test_a_hidden_dependent_is_not_named_under_dependencies() -> None:
    parent = WDKEnumParam.model_validate(
        {
            "name": "organism",
            "type": "single-pick-vocabulary",
            "dependentParams": ["hidden_strain"],
            "vocabulary": _vocab("pfal"),
        }
    )
    hidden_child = WDKEnumParam.model_validate(
        {
            "name": "hidden_strain",
            "type": "single-pick-vocabulary",
            "isVisible": False,
            "vocabulary": _vocab("3D7"),
        }
    )

    overview = _overview([parent, hidden_child])

    assert overview.dependencies == {}
    assert [p.name for p in overview.required] == ["organism"]


def test_hidden_params_are_not_in_the_overview() -> None:
    hidden = WDKStringParam.model_validate(
        {"name": "WebServicesPath", "isVisible": False, "allowEmptyValue": False}
    )
    visible = WDKStringParam.model_validate({"name": "text", "allowEmptyValue": False})

    overview = _overview([hidden, visible])

    assert [p.name for p in overview.required] == ["text"]
    assert overview.optional == []
