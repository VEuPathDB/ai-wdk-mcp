"""What a parameter name alone says about its role in a contrast."""

from __future__ import annotations

from veupathdb.domain.parameters.wdk_vocab import VocabOption

from veupathdb_mcp.catalog.param_formatting import ParameterInfo
from veupathdb_mcp.catalog.param_intent import (
    contrast_pair_key,
    contrast_role,
    is_aggregation_param,
    is_direction_param,
    match_option,
)

_OPTIONS = [
    VocabOption(value="Plasmodium falciparum 3D7", display="P. falciparum 3D7"),
    VocabOption(value="Plasmodium vivax P01", display="P. vivax P01"),
]


def _pi(name: str, display_name: str = "") -> ParameterInfo:
    return ParameterInfo(
        name=name,
        display_name=display_name or name,
        type="multi-pick-vocabulary",
        required=True,
        is_visible=True,
        help="",
        value_format="",
    )


class TestMatchOption:
    def test_an_exact_term_wins(self) -> None:
        assert match_option(_OPTIONS, "Plasmodium vivax P01") == "Plasmodium vivax P01"

    def test_an_exact_label_wins(self) -> None:
        assert match_option(_OPTIONS, "p. vivax p01") == "Plasmodium vivax P01"

    def test_a_substring_falls_back_to_the_first_containing_entry(self) -> None:
        assert match_option(_OPTIONS, "vivax") == "Plasmodium vivax P01"

    def test_no_entry_matches_returns_none(self) -> None:
        assert match_option(_OPTIONS, "Toxoplasma gondii ME49") is None


class TestContrastRole:
    def test_a_comparison_sample_selector_is_the_comparison_side(self) -> None:
        assert contrast_role(_pi("samples_fc_comp_generic")) == "comparison"

    def test_a_reference_sample_selector_is_the_reference_side(self) -> None:
        assert contrast_role(_pi("samples_fc_ref_generic")) == "reference"

    def test_the_display_name_decides_when_the_name_does_not(self) -> None:
        assert contrast_role(_pi("group_a", "Comparison Group")) == "comparison"

    def test_a_param_that_names_no_sample_group_has_no_role(self) -> None:
        assert contrast_role(_pi("regulated_dir")) is None

    def test_an_aggregation_selector_has_no_role(self) -> None:
        assert contrast_role(_pi("min_max_avg_ref")) is None


class TestIsAggregationParam:
    def test_a_min_max_avg_selector_is_an_aggregation(self) -> None:
        assert is_aggregation_param("min_max_avg_comp")

    def test_an_operation_selector_is_an_aggregation(self) -> None:
        assert is_aggregation_param("Operation Applied to Reference Samples")

    def test_a_sample_selector_is_not(self) -> None:
        assert not is_aggregation_param("samples_fc_comp_generic")


class TestIsDirectionParam:
    """The ledger labels a bound direction, so the name test is its only input."""

    def test_the_wdk_fold_change_direction_param(self) -> None:
        assert is_direction_param("regulated_dir")

    def test_a_name_ending_in_the_dir_suffix(self) -> None:
        assert is_direction_param("expression_dir")

    def test_a_name_spelling_direction_out(self) -> None:
        assert is_direction_param("Regulation Direction")

    def test_a_sample_selector_is_not_a_direction(self) -> None:
        assert not is_direction_param("samples_fc_comp_generic")

    def test_a_name_merely_containing_dir_is_not_a_direction(self) -> None:
        assert not is_direction_param("dirty_read")


class TestContrastPairKey:
    def test_the_two_halves_of_one_pair_share_a_key(self) -> None:
        assert contrast_pair_key("samples_fc_ref_generic") == contrast_pair_key(
            "samples_fc_comp_generic"
        )

    def test_unrelated_pairs_keep_different_keys(self) -> None:
        assert contrast_pair_key("samples_fc_ref_generic") != contrast_pair_key(
            "samples_de_ref_deseq"
        )

    def test_a_name_without_a_role_marker_is_its_own_key(self) -> None:
        assert contrast_pair_key("regulated_dir") == "regulated_dir"
