"""Binding one proposed value to one parameter: vocabulary match, defaults, ledger."""

from __future__ import annotations

from veupathdb.domain.parameters import (
    FAKE_ALL_SENTINEL,
    MultiPickValue,
    NumberValue,
    SinglePickValue,
    StringValue,
    VocabOption,
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
    flatten_vocab,
)

from veupathdb_mcp.catalog._param_binding import (
    _apply_override,
    _open_slot,
    _scalar_default,
    _single_valid_value,
    _vocab_signature,
    _VocabLedger,
    param_value_for,
)
from veupathdb_mcp.catalog.param_formatting import ParameterInfo

from .conftest import param_info, vocab

_HOURS = [f"{h} Hour" for h in range(1, 49)]
_TROPHOZOITE = [f"{h} Hour" for h in range(20, 33)]


def _many(n: int) -> list[VocabOption]:
    return [VocabOption(value=f"GO:{i:07d}", display=f"term {i}") for i in range(n)]


def _go_param(
    *, allowed: list[VocabOption] | None, leaves: list[VocabOption]
) -> ParameterInfo:
    return param_info(
        "go_typeahead",
        "multi-pick-vocabulary",
        display_name="GO term",
        allowed=allowed,
        leaves=leaves,
    )


def _tree_box_organism() -> ParameterInfo:
    return param_info(
        "organism",
        "multi-pick-vocabulary",
        leaves=[
            VocabOption(value="Plasmodium vivax P01", display="P. vivax P01"),
            VocabOption(
                value="Plasmodium falciparum 3D7", display="Plasmodium falciparum 3D7"
            ),
        ],
    )


def _samples_param() -> ParameterInfo:
    return param_info(
        "samples_percentile_generic",
        "multi-pick-vocabulary",
        display_name="Samples",
        leaves=vocab(*_HOURS),
    )


def _numeric(name: str, default: str) -> ParameterInfo:
    return param_info(name, "string", is_number=True, default=default)


def _free_text(name: str, default: str) -> ParameterInfo:
    return param_info(name, "string", default=default)


class TestParamValueFor:
    def test_a_multipick_wraps_a_bare_term_as_a_json_array(self) -> None:
        value = param_value_for(
            param_info("organism", "multi-pick-vocabulary"),
            "Plasmodium falciparum 3D7",
        )

        assert isinstance(value, MultiPickValue)
        assert value.values == ["Plasmodium falciparum 3D7"]
        assert value.to_wire() == '["Plasmodium falciparum 3D7"]'

    def test_scalars(self) -> None:
        number = param_value_for(param_info("min_tm", "number"), "2")
        assert isinstance(number, NumberValue)
        assert number.value == 2.0

        single = param_value_for(param_info("go_term_evidence"), "Curated")
        assert isinstance(single, SinglePickValue)
        assert single.value == "Curated"

    def test_a_resolved_numeric_default_is_a_string_param_value(self) -> None:
        info = _numeric("dn_ds_ratio_lower", "0")
        value = param_value_for(info, _scalar_default(info) or "")

        assert isinstance(value, StringValue)
        assert value.value == "0"


class TestApplyOverride:
    def test_a_tree_box_leaf_matches_by_term_or_by_label(self) -> None:
        info = _tree_box_organism()

        assert _apply_override(info, "plasmodium vivax p01") == "Plasmodium vivax P01"
        assert _apply_override(info, "P. vivax P01") == "Plasmodium vivax P01"

    def test_a_substring_does_not_snap_to_a_leaf(self) -> None:
        # "Plasmodium vivax" is a genus, not the strain leaf. Snapping it binds a
        # strain the request never named.
        assert (
            _apply_override(_tree_box_organism(), "Plasmodium vivax")
            == "Plasmodium vivax"
        )

    def test_it_matches_beyond_the_wire_cap(self) -> None:
        full = _many(300)

        assert _apply_override(
            _go_param(allowed=full[:50], leaves=full), "term 299"
        ) == ("GO:0000299")

    def test_it_matches_every_element_of_a_list(self) -> None:
        assert _apply_override(_samples_param(), _TROPHOZOITE) == _TROPHOZOITE

    def test_it_snaps_each_element_to_its_vocabulary_entry(self) -> None:
        assert _apply_override(_samples_param(), ["20 hour", "21 HOUR"]) == [
            "20 Hour",
            "21 Hour",
        ]

    def test_it_keeps_an_unmatched_element_for_wdk_to_reject(self) -> None:
        assert _apply_override(_samples_param(), ["20 Hour", "99 Hour"]) == [
            "20 Hour",
            "99 Hour",
        ]

    def test_it_still_handles_a_plain_string(self) -> None:
        assert _apply_override(_samples_param(), "20 Hour") == "20 Hour"

    def test_an_empty_list_stays_empty(self) -> None:
        assert _apply_override(_samples_param(), []) == []


class TestVocabularyIsTheWholeList:
    def test_the_capped_list_is_not_the_vocabulary(self) -> None:
        full = _many(300)

        assert len(_go_param(allowed=full[:50], leaves=full).vocabulary()) == 300

    def test_the_sentinel_is_not_an_option(self) -> None:
        tree = WDKTreeBoxVocabNode(
            data=WDKVocabNodeData(term=FAKE_ALL_SENTINEL, display="All"),
            children=[
                WDKTreeBoxVocabNode(
                    data=WDKVocabNodeData(term="Plasmodium", display="Plasmodium")
                )
            ],
        )

        assert [o.value for o in flatten_vocab(tree)] == ["Plasmodium"]

    def test_a_repeated_option_is_offered_once(self) -> None:
        repeated = VocabOption(value="GO:0000001", display="term 1")
        info = _go_param(
            allowed=None,
            leaves=[
                repeated,
                repeated,
                VocabOption(value="GO:0000002", display="term 2"),
            ],
        )

        assert [o.value for o in info.vocabulary()] == ["GO:0000001", "GO:0000002"]


class TestUnboundParameter:
    def test_it_offers_a_tree_box_vocabulary(self) -> None:
        terms = [f"GO:{i:07d}" for i in range(25)]
        terms.insert(5, terms[3])
        tree = WDKTreeBoxVocabNode(
            data=WDKVocabNodeData(term=FAKE_ALL_SENTINEL, display="All"),
            children=[
                WDKTreeBoxVocabNode(data=WDKVocabNodeData(term=t, display=f"term {t}"))
                for t in terms
            ],
        )

        slot = _open_slot(_go_param(allowed=None, leaves=flatten_vocab(tree)))

        assert FAKE_ALL_SENTINEL not in slot.options
        assert len(set(slot.options)) == len(slot.options)
        assert slot.options == [f"GO:{i:07d}" for i in range(20)]


class TestSingleValidValue:
    def test_a_one_option_vocabulary_has_a_single_valid_value(self) -> None:
        info = param_info(
            "strand", allowed=[VocabOption(value="sense", display="Sense")]
        )

        assert _single_valid_value(info) == "sense"

    def test_a_single_leaf_tree_box_auto_resolves(self) -> None:
        assert _single_valid_value(_go_param(allowed=None, leaves=_many(1))) == (
            "GO:0000000"
        )

    def test_several_options_leave_the_value_to_the_caller(self) -> None:
        info = param_info(
            "strand",
            allowed=[
                VocabOption(value="sense", display="Sense"),
                VocabOption(value="antisense", display="Antisense"),
            ],
            default="sense",
        )

        assert [_single_valid_value(info), [o.value for o in info.vocabulary()]] == [
            None,
            ["sense", "antisense"],
        ]

    def test_no_vocabulary_has_no_single_valid_value(self) -> None:
        info = param_info("text_expression", allowed=None)

        assert [_single_valid_value(info), info.vocabulary()] == [None, []]


class TestTheLedgerSeesTreeBoxVocabularies:
    def test_a_tree_box_param_has_a_signature(self) -> None:
        signature = _vocab_signature(_go_param(allowed=None, leaves=_many(3)))

        assert signature == _vocab_signature(_go_param(allowed=None, leaves=_many(3)))
        assert signature != _vocab_signature(_go_param(allowed=None, leaves=_many(4)))

    def test_a_sibling_taking_a_tree_box_value_is_a_duplicate(self) -> None:
        info = _go_param(allowed=None, leaves=_many(3))
        signature = _vocab_signature(info)
        assert signature is not None
        ledger = _VocabLedger()
        ledger.claim(signature, "GO:0000001", "sample_ref", pinned=True)

        assert ledger.duplicates_sibling(info, "GO:0000001")


class TestScalarDefaults:
    def test_a_zero_lower_bound_resolves(self) -> None:
        assert _scalar_default(_numeric("dn_ds_ratio_lower", "0")) == "0"

    def test_a_curated_non_zero_default_resolves(self) -> None:
        # WDK ships 20 here; asking the user is less faithful than using it.
        assert _scalar_default(_numeric("MinPercentIsolateCalls", "20")) == "20"

    def test_every_snp_bound_from_the_live_search_resolves(self) -> None:
        live = {
            "MinPercentMinorAlleles": "0",
            "MinPercentIsolateCalls": "20",
            "occurrences_lower": "0",
            "dn_ds_ratio_lower": "0",
            "snp_density_lower": "0",
        }

        unresolved = [
            name
            for name, default in live.items()
            if _scalar_default(_numeric(name, default)) is None
        ]

        assert unresolved == []

    def test_a_text_query_example_is_not_inherited(self) -> None:
        # A search-text default is an example in the form, so binding it would
        # rewrite the question.
        info = _free_text("text_expression", "*reductase")

        assert [_scalar_default(info), info.default_value] == [None, "*reductase"]

    def test_a_number_flagged_search_text_is_still_suppressed(self) -> None:
        info = _free_text("text_expression", "odorant")

        assert [_scalar_default(info), info.default_value] == [None, "odorant"]
