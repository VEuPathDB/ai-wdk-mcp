"""The parameters an analysis run sends: the form's defaults under the caller's."""

import pytest
from pydantic import TypeAdapter
from veupathdb.wdk import WDKEnumParam, WDKNumberParam, WDKParameter

from veupathdb_mcp.wdk import merge_analysis_params


def _form() -> list[WDKParameter]:
    return [
        WDKEnumParam(
            name="organism",
            display_name="Organism",
            type="single-pick-vocabulary",
            initial_display_value="Plasmodium falciparum 3D7",
        ),
        WDKEnumParam(
            name="goEvidenceCodes",
            display_name="Evidence",
            type="multi-pick-vocabulary",
            initial_display_value='["Computed","Curated"]',
        ),
        WDKNumberParam(
            name="pValueCutoff",
            display_name="P-value cutoff",
            initial_display_value="0.05",
        ),
    ]


class TestTheDefaultsTheFormStated:
    def test_an_unnamed_parameter_keeps_the_value_the_form_offered(self) -> None:
        merged = merge_analysis_params(_form(), {})

        assert merged == {
            "organism": "Plasmodium falciparum 3D7",
            "goEvidenceCodes": '["Computed","Curated"]',
            "pValueCutoff": "0.05",
        }


class TestASuppliedValueGoesOnTheWireForItsKind:
    def test_a_single_pick_term_replaces_the_default_unwrapped(self) -> None:
        merged = merge_analysis_params(_form(), {"organism": "Plasmodium vivax P01"})

        assert merged["organism"] == "Plasmodium vivax P01"

    def test_a_multi_pick_selection_is_a_json_array(self) -> None:
        merged = merge_analysis_params(
            _form(), {"goEvidenceCodes": ["Computed", "Curated"]}
        )

        assert merged["goEvidenceCodes"] == '["Computed", "Curated"]'

    def test_a_name_the_form_does_not_declare_is_carried_as_it_came(self) -> None:
        merged = merge_analysis_params(_form(), {"goSubset": "No"})

        assert merged["goSubset"] == "No"

    def test_a_supplied_number_takes_the_canonical_form_of_its_kind(self) -> None:
        merged = merge_analysis_params(_form(), {"pValueCutoff": "1.0"})

        assert merged["pValueCutoff"] == "1"


class TestAStructuralValueSuppliedAsAWireStringIsRefused:
    def test_a_range_parameter_refuses_the_string_form(self) -> None:
        span = TypeAdapter(WDKParameter).validate_python(
            {"name": "span", "displayName": "Span", "type": "number-range"}
        )

        with pytest.raises(ValueError, match="number-range"):
            merge_analysis_params([span], {"span": '{"min": 2, "max": 4}'})
