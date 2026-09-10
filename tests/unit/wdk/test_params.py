"""WDK vocabulary parameter encoding, and the defaults a form offers."""

from veupathdb.domain.parameters.wdk_vocab import (
    FAKE_ALL_SENTINEL,
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
)
from veupathdb.wdk.wdk_parameters import (
    WDKEnumParam,
    WDKNumberParam,
    WDKParameter,
    WDKStringParam,
)

from veupathdb_mcp.wdk import (
    encode_vocab_params,
    encode_vocab_value,
    extract_default_params,
    extract_vocab_values,
)


def _form() -> list[WDKParameter]:
    return [
        WDKStringParam(
            name="organism",
            display_name="Organism",
            initial_display_value="Plasmodium falciparum 3D7",
        ),
        WDKNumberParam(
            name="pValueCutoff",
            display_name="P-value cutoff",
            initial_display_value="0.05",
        ),
    ]


class TestTheFormDefaultsAreCarriedBack:
    """Creation validates with no fill, so every offered value is sent back."""

    def test_every_offered_value_is_copied(self) -> None:
        defaults = extract_default_params(_form())

        assert set(defaults) == {"organism", "pValueCutoff"}

    def test_the_values_are_the_ones_the_form_offered(self) -> None:
        defaults = extract_default_params(_form())

        assert defaults["organism"] == "Plasmodium falciparum 3D7"
        assert defaults["pValueCutoff"] == "0.05"

    def test_a_param_the_form_left_empty_is_not_invented(self) -> None:
        # An absent default is the case creation rejects. A made-up value would
        # hide that rejection behind a wrong result.
        form = [WDKStringParam(name="organism", display_name="Organism"), *_form()[1:]]

        assert "organism" not in extract_default_params(form)


class TestVocabularyValuesAreJsonArrays:
    """WDK reads a vocabulary stable value with ``new JSONArray(stableValue)``."""

    def test_a_plain_value_is_wrapped(self) -> None:
        assert encode_vocab_value("Molecular Function") == '["Molecular Function"]'

    def test_a_value_that_is_already_an_array_is_kept(self) -> None:
        assert encode_vocab_value('["a", "b"]') == '["a", "b"]'

    def test_a_vocabulary_param_is_encoded_and_the_others_are_not(self) -> None:
        params = encode_vocab_params(
            {"goAssociationsOntologies": "Molecular Function", "pValueCutoff": "0.05"},
            [
                WDKEnumParam(
                    name="goAssociationsOntologies",
                    display_name="Ontology",
                    type="single-pick-vocabulary",
                ),
                WDKNumberParam(name="pValueCutoff", display_name="P-value"),
            ],
        )

        assert params == {
            "goAssociationsOntologies": '["Molecular Function"]',
            "pValueCutoff": "0.05",
        }

    def test_a_value_the_form_does_not_name_is_left_alone(self) -> None:
        params = encode_vocab_params(
            {"organism": "Plasmodium falciparum 3D7"},
            [WDKNumberParam(name="pValueCutoff", display_name="P-value")],
        )

        assert params == {"organism": "Plasmodium falciparum 3D7"}

    def test_a_vocabulary_value_that_is_not_a_string_is_left_alone(self) -> None:
        params = encode_vocab_params(
            {"goAssociationsOntologies": ["Molecular Function"]},
            [
                WDKEnumParam(
                    name="goAssociationsOntologies",
                    display_name="Ontology",
                    type="single-pick-vocabulary",
                )
            ],
        )

        assert params == {"goAssociationsOntologies": ["Molecular Function"]}


class TestTheVocabularyAParamOffers:
    def test_the_terms_of_the_named_param_are_returned(self) -> None:
        param = WDKEnumParam(
            name="organism",
            display_name="Organism",
            type="multi-pick-vocabulary",
            vocabulary=[["pf3d7", "P. falciparum 3D7", None]],
        )

        assert extract_vocab_values([param], "organism") == ["pf3d7"]

    def test_a_tree_box_vocabulary_offers_its_terms(self) -> None:
        """A tree box is a vocabulary too, so its nodes are the values on offer."""
        param = WDKEnumParam(
            name="organism",
            display_name="Organism",
            type="multi-pick-vocabulary",
            vocabulary=WDKTreeBoxVocabNode(
                data=WDKVocabNodeData(term=FAKE_ALL_SENTINEL, display="All"),
                children=[
                    WDKTreeBoxVocabNode(
                        data=WDKVocabNodeData(term="pf3d7", display="P. falciparum 3D7")
                    ),
                    WDKTreeBoxVocabNode(
                        data=WDKVocabNodeData(term="pvivax", display="P. vivax")
                    ),
                ],
            ),
        )

        assert extract_vocab_values([param], "organism") == ["pf3d7", "pvivax"]

    def test_a_nested_tree_box_offers_only_its_leaves(self) -> None:
        """A clade node groups organisms and is not a term WDK accepts."""
        param = WDKEnumParam(
            name="organism",
            display_name="Organism",
            type="multi-pick-vocabulary",
            vocabulary=WDKTreeBoxVocabNode(
                data=WDKVocabNodeData(term=FAKE_ALL_SENTINEL, display="All"),
                children=[
                    WDKTreeBoxVocabNode(
                        data=WDKVocabNodeData(term="Plasmodium", display="Plasmodium"),
                        children=[
                            WDKTreeBoxVocabNode(
                                data=WDKVocabNodeData(
                                    term="pf3d7", display="P. falciparum 3D7"
                                )
                            ),
                            WDKTreeBoxVocabNode(
                                data=WDKVocabNodeData(term="pvivax", display="P. vivax")
                            ),
                        ],
                    ),
                    WDKTreeBoxVocabNode(
                        data=WDKVocabNodeData(term="tgondii", display="T. gondii ME49")
                    ),
                ],
            ),
        )

        assert extract_vocab_values([param], "organism") == [
            "pf3d7",
            "pvivax",
            "tgondii",
        ]

    def test_a_param_with_no_vocabulary_offers_nothing(self) -> None:
        param = WDKStringParam(name="organism", display_name="Organism")

        assert extract_vocab_values([param], "organism") == []

    def test_a_param_that_is_not_there_offers_nothing(self) -> None:
        assert extract_vocab_values([], "organism") == []
