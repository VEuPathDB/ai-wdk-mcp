"""What a search document publishes, and what a search config keeps apart.

``getRequiredParams()`` returns the whole parameter map and the validation loop
iterates it unfiltered, so ``isVisible`` decides nothing but drawing. Three
unrelated mechanisms are called filters, and the validation level enum is not
closed.
"""

from __future__ import annotations

import json

from veupathdb.domain.parameters import (
    FilterTermClause,
    FilterValue,
    ParamSpecNormalized,
    fill_hidden_required_defaults,
    filled_hidden_defaults,
    topological_fill_order,
)
from veupathdb.domain.strategy import StepValidation
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import (
    WDKFilterValue,
    WDKReporter,
    WDKSearch,
    WDKSearchConfig,
    WDKSearchResponse,
    WDKStepAnalysisTypeResponse,
)

from veupathdb_mcp.catalog.param_adapters import adapt_param_specs_from_search

_SCHEMA_LEVELS = frozenset({"NONE", "UNSPECIFIED", "SYNTACTIC", "SEMANTIC", "RUNNABLE"})


def _search(name: str) -> WDKSearch:
    return WDKSearchResponse.model_validate(load_recorded(name).json_body()).search_data


def _specs_with_dependents(
    dependents: tuple[str, ...],
) -> dict[str, ParamSpecNormalized]:
    return {
        "a": ParamSpecNormalized(
            name="a", param_type="string", dependent_params=dependents
        ),
        "b": ParamSpecNormalized(name="b", param_type="string"),
        "c": ParamSpecNormalized(name="c", param_type="string"),
    }


class TestWdkParam011HiddenIsPresentationOnly:
    def test_wdk_param_011_a_hidden_parameter_is_published(self) -> None:
        search = _search("search_with_a_hidden_required_parameter")

        hidden = [p for p in search.parameters or [] if not p.is_visible]

        assert [p.name for p in hidden] == ["eda_dataset_id"]

    def test_wdk_param_011_a_hidden_parameter_is_in_param_names(self) -> None:
        search = _search("search_with_a_hidden_required_parameter")

        assert "eda_dataset_id" in search.param_names

    def test_wdk_param_011_a_hidden_parameter_stays_required(self) -> None:
        search = _search("search_with_a_hidden_required_parameter")
        specs = adapt_param_specs_from_search(search)

        assert specs["eda_dataset_id"].allow_empty_value is False
        assert specs["eda_dataset_id"].initial_display_value

    def test_wdk_param_011_a_hidden_parameter_survives_normalization(self) -> None:
        search = _search("search_with_a_hidden_required_parameter")

        specs = adapt_param_specs_from_search(search)

        assert sorted(specs) == sorted(search.param_names)

    def test_wdk_param_011_a_client_must_supply_it_so_pathfinder_fills_it(self) -> None:
        specs = adapt_param_specs_from_search(
            _search("search_with_a_hidden_required_parameter")
        )

        filled = fill_hidden_required_defaults(specs, {})

        assert "eda_dataset_id" in filled
        assert filled_hidden_defaults(specs, {}) == ["eda_dataset_id"]


class TestWdkVocab003DependentParamsPointsAtChildren:
    def test_wdk_vocab_003_the_field_lists_the_parameters_that_depend_on_it(
        self,
    ) -> None:
        specs = adapt_param_specs_from_search(_search("search_genes_by_location"))

        assert specs["organismSinglePick"].dependent_params == ("chromosomeOptional",)

    def test_wdk_vocab_003_the_parameter_that_depends_reports_nothing(self) -> None:
        # To find a parameter's parents you invert the map; no field gives them.
        specs = adapt_param_specs_from_search(_search("search_genes_by_location"))

        assert specs["chromosomeOptional"].dependent_params == ()

    def test_wdk_vocab_003_the_parents_come_from_inverting_the_map(self) -> None:
        specs = adapt_param_specs_from_search(_search("search_genes_by_location"))

        parents = {
            child: {n for n, s in specs.items() if child in s.dependent_params}
            for child in specs
        }

        assert parents["chromosomeOptional"] == {"organismSinglePick"}
        assert parents["organismSinglePick"] == set()

    def test_wdk_vocab_003_the_order_of_the_list_changes_nothing(self) -> None:
        # The backing collection is a HashSet, so the same dependency set
        # arrives in a different order on the next search. Compare as sets.
        forwards = topological_fill_order(_specs_with_dependents(("b", "c")))
        backwards = topological_fill_order(_specs_with_dependents(("c", "b")))

        assert set(forwards) == set(backwards)
        for order in (forwards, backwards):
            assert order.index("a") < min(order.index("b"), order.index("c"))


class TestWdkAns006ScopesAreAdviceToTheClient:
    def test_wdk_ans_006_an_empty_scope_list_is_not_a_closed_door(self) -> None:
        reporter = WDKReporter(name="json", scopes=[])

        assert reporter.name == "json"
        assert reporter.scopes == []


class TestWdkFilter001ThreeMechanismsInThreePlaces:
    def test_wdk_filter_001_the_search_config_keeps_them_apart(self) -> None:
        assert {"parameters", "filters", "column_filters"} <= set(
            WDKSearchConfig.model_fields
        )

    def test_wdk_filter_001_a_filter_parameter_lives_among_the_parameters(self) -> None:
        # It is a parameter, so it validates like one and is part of the
        # step's identity.
        value = FilterValue(filters=[FilterTermClause(field="organism")])
        config = WDKSearchConfig(parameters={"organism_filter": value.to_wire()})

        assert (
            json.loads(config.parameters["organism_filter"])["filters"][0]["field"]
            == "organism"
        )

    def test_wdk_filter_001_a_declared_filter_is_a_name_and_a_value(self) -> None:
        config = WDKSearchConfig(
            filters=[WDKFilterValue(name="always_applied", value=None, disabled=False)]
        )

        assert set(config.filters[0].model_dump(by_alias=True)) == {
            "name",
            "value",
            "disabled",
        }

    def test_wdk_filter_001_a_column_filter_is_keyed_by_column_then_tool(self) -> None:
        config = WDKSearchConfig(
            columnFilters={"gene_product": {"byValue": {"pattern": "kinase"}}}
        )

        assert config.column_filters == {
            "gene_product": {"byValue": {"pattern": "kinase"}}
        }

    def test_wdk_filter_001_view_filters_are_a_fourth_name_elsewhere(self) -> None:
        # viewFilters belongs at the top level of a report body, not here.
        config = WDKSearchConfig(
            parameters={"a": "1"},
            filters=[WDKFilterValue(name="f", value=None, disabled=False)],
        )

        assert "viewFilters" not in config.model_dump(
            by_alias=True, exclude_defaults=True
        )


class TestWdkValid007TheLevelEnumIsNotClosed:
    def test_wdk_valid_007_a_displayable_bundle_parses(self) -> None:
        # The form service builds at a level the step schema does not list.
        bundle = StepValidation.model_validate(
            {"level": "DISPLAYABLE", "isValid": True}
        )

        assert bundle.level == "DISPLAYABLE"
        assert bundle.level not in _SCHEMA_LEVELS

    def test_wdk_valid_007_an_analysis_type_response_carries_it(self) -> None:
        response = WDKStepAnalysisTypeResponse.model_validate(
            {
                "searchData": {"name": "word-enrichment", "displayName": "Words"},
                "validation": {"level": "DISPLAYABLE", "isValid": True},
            }
        )

        assert response.validation.level == "DISPLAYABLE"

    def test_wdk_valid_007_the_level_is_a_string_and_not_an_enum(self) -> None:
        assert StepValidation.model_fields["level"].annotation is str

    def test_wdk_valid_007_an_unchecked_level_still_reads_as_unchecked(self) -> None:
        displayable = StepValidation(level="DISPLAYABLE", is_valid=True)

        assert displayable.was_checked()
        assert not displayable.rejects()
