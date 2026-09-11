"""The synthetic tree root is not a value, so nothing offers it as one."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters import (
    FAKE_ALL_SENTINEL,
    MultiPickValue,
    ParameterCanonicalizer,
    ParamSpecNormalized,
    SinglePickValue,
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
)
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog import param_formatting
from veupathdb_mcp.catalog.vocab_rendering import render_vocab_tree


def _tree() -> WDKTreeBoxVocabNode:
    return WDKTreeBoxVocabNode(
        data=WDKVocabNodeData(term=FAKE_ALL_SENTINEL, display="All"),
        children=[
            WDKTreeBoxVocabNode(
                data=WDKVocabNodeData(term="Plasmodium", display="Plasmodium"),
                children=[
                    WDKTreeBoxVocabNode(
                        data=WDKVocabNodeData(term="Pf3D7", display="Pf3D7")
                    )
                ],
            )
        ],
    )


class TestNothingOffersTheSentinel:
    def test_no_model_facing_help_names_it(self) -> None:
        offending = [
            name
            for name, text in vars(param_formatting).items()
            if isinstance(text, str) and FAKE_ALL_SENTINEL in text
        ]

        assert offending == [], (
            f"{offending} tells the model to send a value the system rejects"
        )

    def test_the_rendered_tree_omits_it(self) -> None:
        assert render_vocab_tree(_tree(), max_lines=20) == [
            "  Plasmodium",
            "    Pf3D7",
        ]


class TestTheSystemRefusesIt:
    def test_a_bare_sentinel_is_rejected(self) -> None:
        specs = {
            "organism": ParamSpecNormalized(
                name="organism", param_type="single-pick-vocabulary"
            )
        }

        with pytest.raises(ValidationError):
            ParameterCanonicalizer(specs).canonicalize(
                {"organism": SinglePickValue(value=FAKE_ALL_SENTINEL)}
            )

    def test_a_sentinel_inside_a_selection_is_rejected(self) -> None:
        specs = {
            "organism": ParamSpecNormalized(
                name="organism", param_type="multi-pick-vocabulary"
            )
        }

        with pytest.raises(ValidationError):
            ParameterCanonicalizer(specs).canonicalize(
                {"organism": MultiPickValue(values=["Pf3D7", FAKE_ALL_SENTINEL])}
            )
