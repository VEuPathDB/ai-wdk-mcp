"""One criterion offered twice is stated once, in the vocabulary half."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters import VocabOption

from veupathdb_mcp.catalog.param_formatting import ParameterInfo
from veupathdb_mcp.catalog.radio_pairs import (
    RADIO_OFF,
    RadioPair,
    check_radio_pairs,
    radio_pairs,
)

_EC_ENTRIES = ["2.7.-.-", "2.7.11.1", "3.4.21.-", "1.1.1.1"]


def _vocab(name: str, values: list[str], default: str) -> ParameterInfo:
    return ParameterInfo(
        name=name,
        display_name=name,
        type="single-pick-vocabulary",
        required=True,
        is_visible=True,
        help="",
        value_format="",
        default_value=default,
        vocab_leaves=[VocabOption(value=v, display=v) for v in values],
    )


def _free_text(name: str, default: str) -> ParameterInfo:
    return ParameterInfo(
        name=name,
        display_name=name,
        type="string",
        required=True,
        is_visible=True,
        help="",
        value_format="",
        default_value=default,
    )


def _ec_sheet() -> list[ParameterInfo]:
    return [
        _vocab("ec_number_pattern", _EC_ENTRIES, "2.7.11.1"),
        _free_text("ec_wildcard", RADIO_OFF),
    ]


_EC_PROPERTIES = {"radio-params": ["ec_number_pattern", "ec_wildcard"]}

_GO_PROPERTIES = {"radio-params": ["go_typeahead", "go_term"]}

_TWO_PAIR_PROPERTIES = {
    "radio-params": ["go_typeahead", "go_term", "ec_number_pattern", "ec_wildcard"]
}


def _go_sheet() -> list[ParameterInfo]:
    return [
        _vocab("go_typeahead", ["GO:0004672 : protein kinase activity"], "[]"),
        _free_text("go_term", RADIO_OFF),
    ]


class TestTheDeclaredPairs:
    def test_the_vocabulary_half_is_named_first(self) -> None:
        assert radio_pairs(_EC_PROPERTIES) == [
            RadioPair(vocabulary="ec_number_pattern", free_text="ec_wildcard")
        ]

    def test_a_search_declaring_no_pair_has_none(self) -> None:
        assert radio_pairs({"websiteProperties": ["something"]}) == []

    def test_two_pairs_are_read_two_at_a_time(self) -> None:
        pairs = radio_pairs(_TWO_PAIR_PROPERTIES)

        assert [p.free_text for p in pairs] == ["go_term", "ec_wildcard"]

    def test_an_odd_name_states_no_pair(self) -> None:
        assert radio_pairs({"radio-params": ["go_typeahead"]}) == []


class TestTheFreeTextHalfIsSwitchedOff:
    @pytest.mark.parametrize(
        "proposals",
        [
            {"ec_number_pattern": "2.7.-.-"},
            {"ec_number_pattern": "2.7.-.-", "ec_wildcard": None},
            {"ec_number_pattern": "2.7.-.-", "ec_wildcard": "  "},
            {"ec_number_pattern": "2.7.-.-", "ec_wildcard": "n/a"},
        ],
    )
    def test_a_half_that_states_nothing_takes_the_off_value(
        self, proposals: dict[str, str | list[str] | None]
    ) -> None:
        overrides, issue = check_radio_pairs(
            radio_pairs(_EC_PROPERTIES), _ec_sheet(), proposals
        )

        assert overrides == {"ec_wildcard": RADIO_OFF}
        assert issue is None

    def test_a_search_without_the_pair_is_untouched(self) -> None:
        overrides, issue = check_radio_pairs([], _ec_sheet(), {"ec_wildcard": "2.7.*"})

        assert overrides == {}
        assert issue is None

    def test_a_pair_whose_halves_are_not_both_on_the_sheet_is_skipped(self) -> None:
        overrides, issue = check_radio_pairs(
            radio_pairs(_EC_PROPERTIES),
            [_vocab("ec_number_pattern", _EC_ENTRIES, "2.7.11.1")],
            {},
        )

        assert overrides == {}
        assert issue is None


class TestTheDeclaredShapeDecidesWhichHalfIsWhich:
    """The vocabulary half holds a vocabulary and the free-text half holds none.

    The property names the halves in that order on the searches measured, and a
    declaration in the other order states a different shape than this rule reads.
    """

    def test_the_declared_order_is_taken_when_the_shape_matches(self) -> None:
        overrides, issue = check_radio_pairs(
            radio_pairs(_EC_PROPERTIES), _ec_sheet(), {}
        )

        assert overrides == {"ec_wildcard": RADIO_OFF}
        assert issue is None

    def test_a_reversed_declaration_is_skipped(self) -> None:
        reversed_pairs = radio_pairs(
            {"radio-params": ["ec_wildcard", "ec_number_pattern"]}
        )

        overrides, issue = check_radio_pairs(
            reversed_pairs, _ec_sheet(), {"ec_number_pattern": "2.7.-.-"}
        )

        assert overrides == {}
        assert issue is None

    def test_two_vocabulary_halves_are_skipped(self) -> None:
        sheet = [
            _vocab("ec_number_pattern", _EC_ENTRIES, "2.7.11.1"),
            _vocab("ec_wildcard", ["2.7.*"], RADIO_OFF),
        ]

        overrides, issue = check_radio_pairs(radio_pairs(_EC_PROPERTIES), sheet, {})

        assert overrides == {}
        assert issue is None


class TestAFilledFreeTextHalfIsAnIssue:
    def test_a_wildcard_names_the_entries_it_starts(self) -> None:
        _, issue = check_radio_pairs(
            radio_pairs(_EC_PROPERTIES),
            _ec_sheet(),
            {"ec_number_pattern": None, "ec_wildcard": "2.7.*"},
        )

        assert issue is not None
        assert issue.pair.vocabulary == "ec_number_pattern"
        assert issue.free_value == "2.7.*"
        assert issue.nearest[:2] == ["2.7.-.-", "2.7.11.1"]

    def test_a_word_wildcard_is_an_issue_too(self) -> None:
        _, issue = check_radio_pairs(
            radio_pairs(_EC_PROPERTIES), _ec_sheet(), {"ec_wildcard": "*kinase*"}
        )

        assert issue is not None
        assert issue.free_value == "*kinase*"

    def test_a_listed_value_is_an_issue(self) -> None:
        _, issue = check_radio_pairs(
            radio_pairs(_EC_PROPERTIES), _ec_sheet(), {"ec_wildcard": ["*kinase*"]}
        )

        assert issue is not None
        assert issue.free_value == "*kinase*"

    def test_every_other_pair_keeps_its_off_value(self) -> None:
        # An issue on one pair leaves the other halves stating nothing, so they
        # take the off value whichever pair is refused.
        sheet = [*_go_sheet(), *_ec_sheet()]

        overrides, issue = check_radio_pairs(
            radio_pairs(_TWO_PAIR_PROPERTIES), sheet, {"go_term": "*kinase*"}
        )

        assert overrides == {"ec_wildcard": RADIO_OFF}
        assert issue is not None
        assert issue.pair.free_text == "go_term"
