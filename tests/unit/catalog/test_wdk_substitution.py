"""WDK reports which values it supplied, and that report outranks ours."""

from __future__ import annotations

from veupathdb.domain.parameters.specs import ParamSpecNormalized
from veupathdb.domain.parameters.value_codec import from_wire
from veupathdb.domain.parameters.values import (
    FilterTermClause,
    FilterValue,
    InputStepValue,
    MultiPickValue,
    NumberValue,
    SinglePickValue,
    StringValue,
)

from veupathdb_mcp.catalog.wdk_substitution import substituted_params


def _spec(name: str, param_type: str = "string") -> ParamSpecNormalized:
    return ParamSpecNormalized(name=name, param_type=param_type)


_SPECS = {
    "organism": _spec("organism", "single-pick-vocabulary"),
    "min_weight": _spec("min_weight", "number"),
    "fold_change": _spec("fold_change", "number"),
    "samples": _spec("samples", "multi-pick-vocabulary"),
    "profile_pattern": _spec("profile_pattern"),
    "phyletic_term_map": _spec("phyletic_term_map", "multi-pick-vocabulary"),
    "a": _spec("a"),
    "b": _spec("b"),
}


class TestWhatWDKFilledIn:
    def test_a_param_we_did_not_send_is_substituted(self) -> None:
        filled = substituted_params(
            sent={"organism": SinglePickValue(value="Pf")},
            echoed={"organism": "Pf", "min_weight": "10000"},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == ["min_weight"]

    def test_a_param_we_sent_is_not_substituted(self) -> None:
        filled = substituted_params(
            sent={"organism": SinglePickValue(value="Pf")},
            echoed={"organism": "Pf"},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == []

    def test_a_value_wdk_replaced_counts_as_substituted(self) -> None:
        # An unknown term comes back as the empty selection, which is WDK
        # choosing a value rather than accepting ours.
        filled = substituted_params(
            sent={"organism": SinglePickValue(value="Nonexistent")},
            echoed={"organism": "[]"},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == ["organism"]

    def test_a_scalar_wdk_echoes_differently_is_substituted(self) -> None:
        filled = substituted_params(
            sent={"profile_pattern": StringValue(value="%hsap:N%pfal:Y%")},
            echoed={"profile_pattern": "hsap=1T"},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == ["profile_pattern"]

    def test_an_unchanged_numeric_is_not_substituted(self) -> None:
        filled = substituted_params(
            sent={"fold_change": NumberValue(value=2)},
            echoed={"fold_change": "2"},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == []


class TestItIsOrderIndependent:
    def test_results_are_sorted(self) -> None:
        filled = substituted_params(
            sent={},
            echoed={"b": "1", "a": "2"},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == ["a", "b"]

    def test_an_echoed_empty_value_is_not_a_substitution(self) -> None:
        # WDK omits a value it has nothing to offer for; an empty string is not
        # a choice it made.
        filled = substituted_params(
            sent={},
            echoed={"a": ""},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == []


class TestAVocabularyIsComparedAsASelection:
    def test_a_branch_expanded_to_leaves_is_not_substituted(self) -> None:
        # The caller proposed a tree parent; the canonical value is its leaves,
        # which is what WDK echoes back.
        filled = substituted_params(
            sent={"samples": MultiPickValue(values=["17 Hour", "18 Hour"])},
            echoed={"samples": '["18 Hour", "17 Hour"]'},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == []

    def test_a_dropped_selection_is_substituted(self) -> None:
        filled = substituted_params(
            sent={"samples": MultiPickValue(values=["17 Hour"])},
            echoed={"samples": "[]"},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == ["samples"]

    def test_an_empty_selection_we_did_not_send_is_not_a_substitution(self) -> None:
        # A structural param that allows empty echoes the empty selection. WDK
        # chose nothing there.
        filled = substituted_params(
            sent={},
            echoed={"phyletic_term_map": "[]"},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == []

    def test_a_single_pick_echoed_as_a_list_is_not_substituted(self) -> None:
        filled = substituted_params(
            sent={"organism": SinglePickValue(value="Pf")},
            echoed={"organism": '["Pf"]'},
            specs=_SPECS,
            values_were_read=True,
        )

        assert filled == []


class TestADefinitionBuiltWithoutOurValues:
    """WDK renders the static spec when the contextual read fails.

    That definition answers a question about no caller at all, so it can only
    report the params the caller left unset.
    """

    def test_a_value_we_sent_is_never_substituted(self) -> None:
        filled = substituted_params(
            sent={"profile_pattern": StringValue(value="%hsap:N%pfal:Y%")},
            echoed={"profile_pattern": "hsap=1T"},
            specs=_SPECS,
            values_were_read=False,
        )

        assert filled == []

    def test_a_param_we_left_unset_still_shows_its_default(self) -> None:
        filled = substituted_params(
            sent={},
            echoed={"min_weight": "10000"},
            specs=_SPECS,
            values_were_read=False,
        )

        assert filled == ["min_weight"]


_FILTER_SPECS = {
    "variation_sample_meta": _spec("variation_sample_meta", "filter"),
    "transcript_result": _spec("transcript_result", "input-step"),
}

_WDK_FILTER_ECHO = (
    '{"filters": [{"value": ["Thailand", "Cambodia"], "includeUnknown": false, '
    '"isRange": false, "type": "string", "field": "VAR_8e68b3e5", '
    '"fieldDisplayName": "Country"}]}'
)
"""What plasmodb echoed for ``GenesByNgsSnps.variation_sample_meta``.

WDK stores the stable value as the caller wrote it, so the echo carries the
key order and the ``fieldDisplayName`` that ``FilterValue.to_wire`` drops::

    curl -X POST -d @context.json 'https://plasmodb.org/plasmo/service/record-types/transcript/searches/GenesByNgsSnps?expandParams=true'
"""


class TestAFilterIsComparedAsItsClauses:
    def test_a_reserialized_filter_is_not_substituted(self) -> None:
        filled = substituted_params(
            sent={"variation_sample_meta": from_wire("filter", _WDK_FILTER_ECHO)},
            echoed={"variation_sample_meta": _WDK_FILTER_ECHO},
            specs=_FILTER_SPECS,
            values_were_read=True,
        )

        assert filled == []

    def test_reordered_clauses_are_not_substituted(self) -> None:
        ours = FilterValue(
            filters=[
                FilterTermClause(field="VAR_country", value=["Thailand"]),
                FilterTermClause(field="VAR_year", value=["2014"]),
            ]
        )
        echoed = (
            '{"filters":[{"field":"VAR_year","value":["2014"]},'
            '{"field":"VAR_country","value":["Thailand"]}]}'
        )

        filled = substituted_params(
            sent={"variation_sample_meta": ours},
            echoed={"variation_sample_meta": echoed},
            specs=_FILTER_SPECS,
            values_were_read=True,
        )

        assert filled == []

    def test_a_reordered_value_set_is_not_substituted(self) -> None:
        ours = FilterValue(
            filters=[FilterTermClause(field="VAR_country", value=["Thailand", "Mali"])]
        )
        echoed = '{"filters":[{"field":"VAR_country","value":["Mali","Thailand"]}]}'

        filled = substituted_params(
            sent={"variation_sample_meta": ours},
            echoed={"variation_sample_meta": echoed},
            specs=_FILTER_SPECS,
            values_were_read=True,
        )

        assert filled == []

    def test_a_dropped_clause_is_substituted(self) -> None:
        ours = FilterValue(
            filters=[
                FilterTermClause(field="VAR_country", value=["Thailand"]),
                FilterTermClause(field="VAR_year", value=["2014"]),
            ]
        )
        echoed = '{"filters":[{"field":"VAR_country","value":["Thailand"]}]}'

        filled = substituted_params(
            sent={"variation_sample_meta": ours},
            echoed={"variation_sample_meta": echoed},
            specs=_FILTER_SPECS,
            values_were_read=True,
        )

        assert filled == ["variation_sample_meta"]

    def test_a_narrowed_value_set_is_substituted(self) -> None:
        ours = FilterValue(
            filters=[FilterTermClause(field="VAR_country", value=["Thailand", "Mali"])]
        )
        echoed = '{"filters":[{"field":"VAR_country","value":["Mali"]}]}'

        filled = substituted_params(
            sent={"variation_sample_meta": ours},
            echoed={"variation_sample_meta": echoed},
            specs=_FILTER_SPECS,
            values_were_read=True,
        )

        assert filled == ["variation_sample_meta"]

    def test_a_flipped_include_unknown_is_substituted(self) -> None:
        ours = FilterValue(
            filters=[FilterTermClause(field="VAR_country", value=["Thailand"])]
        )
        echoed = (
            '{"filters":[{"field":"VAR_country","includeUnknown":true,'
            '"value":["Thailand"]}]}'
        )

        filled = substituted_params(
            sent={"variation_sample_meta": ours},
            echoed={"variation_sample_meta": echoed},
            specs=_FILTER_SPECS,
            values_were_read=True,
        )

        assert filled == ["variation_sample_meta"]


class TestAnInputStepIsNotReported:
    """The wiring of a step to its input is structural, never a WDK choice."""

    def test_an_echoed_step_id_the_caller_never_sent_is_not_substituted(self) -> None:
        filled = substituted_params(
            sent={},
            echoed={"transcript_result": "330423363"},
            specs=_FILTER_SPECS,
            values_were_read=True,
        )

        assert filled == []

    def test_a_step_id_wdk_echoes_differently_is_not_substituted(self) -> None:
        filled = substituted_params(
            sent={"transcript_result": InputStepValue(step_id="1")},
            echoed={"transcript_result": "2"},
            specs=_FILTER_SPECS,
            values_were_read=True,
        )

        assert filled == []
