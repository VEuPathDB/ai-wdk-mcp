"""The wire form of one parameter value, and the defaults a form offers."""

from veupathdb.domain.parameters import (
    FAKE_ALL_SENTINEL,
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
)
from veupathdb.wdk import WDKEnumParam, WDKNumberParam, WDKParameter, WDKStringParam

from veupathdb_mcp.wdk import (
    encode_param_value,
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

    def test_a_vocabulary_default_is_carried_back_unwrapped(self) -> None:
        """WDK states the stable value, so a single pick goes back as it came."""
        form: list[WDKParameter] = [
            WDKEnumParam(
                name="goAssociationsOntologies",
                display_name="Ontology",
                type="single-pick-vocabulary",
                initial_display_value="Biological Process",
            )
        ]

        assert extract_default_params(form) == {
            "goAssociationsOntologies": "Biological Process"
        }

    def test_a_param_the_form_left_empty_is_not_invented(self) -> None:
        # An absent default is the case creation rejects. A made-up value would
        # hide that rejection behind a wrong result.
        form = [WDKStringParam(name="organism", display_name="Organism"), *_form()[1:]]

        assert "organism" not in extract_default_params(form)


class TestTheWireFormIsTheClientsCodec:
    """One codec states every wire form. A single pick is the bare term."""

    def test_a_single_pick_value_is_the_bare_term(self) -> None:
        param = WDKEnumParam(
            name="goAssociationsOntologies",
            display_name="Ontology",
            type="single-pick-vocabulary",
        )

        assert encode_param_value(param, "Molecular Function") == "Molecular Function"

    def test_a_multi_pick_value_is_a_json_array(self) -> None:
        param = WDKEnumParam(
            name="goEvidenceCodes",
            display_name="Evidence",
            type="multi-pick-vocabulary",
        )

        assert encode_param_value(param, ["Computed", "Curated"]) == (
            '["Computed", "Curated"]'
        )

    def test_a_number_keeps_the_value_the_caller_named(self) -> None:
        param = WDKNumberParam(name="pValueCutoff", display_name="P-value")

        assert encode_param_value(param, "0.05") == "0.05"


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
