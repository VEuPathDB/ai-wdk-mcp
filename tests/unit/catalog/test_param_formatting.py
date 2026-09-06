"""Formatting WDK parameter specs into the info objects the model reads."""

from __future__ import annotations

from typing import ClassVar

from veupathdb.domain.parameters.specs import ParamSpecNormalized
from veupathdb.domain.parameters.values import SinglePickValue
from veupathdb.domain.parameters.wdk_vocab import (
    WDKFilterOntologyTerm,
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
    WDKVocabTerm,
)
from veupathdb.wdk.wdk_parameters import (
    WDKEnumParam,
    WDKFilterParam,
    WDKParameter,
    WDKStringParam,
)

from veupathdb_mcp.catalog.param_formatting import (
    ParameterInfo,
    format_normalized_param_info,
    format_param_info_typed,
    format_typed_param,
)
from veupathdb_mcp.catalog.vocab_rendering import _MAX_VOCAB_ENTRIES

from .conftest import param_info, vocab_terms

_PHYLETIC_TERMS = vocab_terms(
    ("ALL", "Root"),
    ("EUKA", "Eukaryota"),
    ("MAMM", "Mammalia"),
    ("hsap", "Homo sapiens REF"),
    ("pfal", "Plasmodium falciparum 3D7"),
)
_PHYLETIC_INDENTS = vocab_terms(
    ("EUKA", "1"), ("MAMM", "2"), ("hsap", "3"), ("pfal", "2")
)
_PHYLETIC_HELP_SENTENCE = (
    "Species or clade codes from the phyletic tree, comma-separated or a list; "
    "a clade selects all of its species; profile_pattern is derived from these "
    "two lists."
)


def _one_leaf_tree(term: str) -> WDKTreeBoxVocabNode:
    return WDKTreeBoxVocabNode(
        data=WDKVocabNodeData(term="root", display="root"),
        children=[WDKTreeBoxVocabNode(data=WDKVocabNodeData(term=term, display=term))],
    )


def _samples(name: str) -> WDKEnumParam:
    return WDKEnumParam(
        name=name,
        display_name="Samples",
        type="multi-pick-vocabulary",
        vocabulary=_one_leaf_tree("20 Hour"),
    )


def test_param_kind_narrows_type_to_typed_paramkind() -> None:
    kinds = [
        "multi-pick-vocabulary",
        "single-pick-vocabulary",
        "number",
        "input-dataset",
    ]

    assert [param_info("p", kind).param_kind for kind in kinds] == kinds


def test_param_kind_falls_back_to_string_for_unknown_type() -> None:
    # The discriminator field `kind` must NOT be mistaken for the param kind.
    info = param_info("p", "SomeUnnormalizedWdkType")

    assert info.kind == "parameter_info"
    assert info.param_kind == "string"


def test_filter_param_exposes_selectable_leaf_facets() -> None:
    # Mirrors live plasmodb ngsSnp_strain_meta: category nodes carry type=None
    # (not selectable); leaf facets carry a type + their valid values.
    param = WDKFilterParam(
        name="ngsSnp_strain_meta",
        display_name="Set of Samples",
        ontology=[
            WDKFilterOntologyTerm(
                term="Sample collection", display="Sample collection"
            ),
            WDKFilterOntologyTerm(
                term="Sample type", display="Sample type", type="string"
            ),
            WDKFilterOntologyTerm(term="Country", display="Country", type="string"),
        ],
        values={
            "Sample type": ["specimen from organism", "culture", "blood"],
            "Country": ["India", "Thailand"],
        },
    )

    info = format_typed_param(param, {}, {})

    assert info.param_kind == "filter"
    fields = {f.term: f for f in info.filter_fields}
    assert set(fields) == {"Sample type", "Country"}  # category node excluded
    assert fields["Sample type"].type == "string"
    assert fields["Sample type"].is_range is False
    assert fields["Sample type"].values == [
        "specimen from organism",
        "culture",
        "blood",
    ]
    assert fields["Country"].values == ["India", "Thailand"]


class TestDependentParamNote:
    """The note must say which parent values produced the list it accompanies.

    Naming the wrong context when the read inherited a bound parent is a lie
    about provenance, and the model sees a plausible list either way.
    """

    _DEPENDS: ClassVar[dict[str, list[str]]] = {
        "samples_percentile_generic": ["profileset_generic"]
    }
    _APPLIED: ClassVar[dict[str, SinglePickValue]] = {
        "profileset_generic": SinglePickValue(value="DeRisi 3D7 Smoothed")
    }

    def _applied_note(self) -> str:
        info = format_typed_param(
            _samples("samples_percentile_generic"),
            self._DEPENDS,
            {},
            applied_context=self._APPLIED,
        )
        assert info.note is not None
        return info.note

    def test_names_the_applied_parent_value(self) -> None:
        assert "DeRisi 3D7 Smoothed" in self._applied_note()

    def test_does_not_claim_default_context_when_one_was_applied(self) -> None:
        assert "No parent value was supplied" not in self._applied_note()

    def test_warns_that_another_parent_yields_another_list(self) -> None:
        assert "DIFFERENT" in self._applied_note()

    def test_falls_back_to_the_default_context_wording(self) -> None:
        info = format_typed_param(
            _samples("samples_percentile_generic"), self._DEPENDS, {}
        )

        assert info.note is not None
        assert "No parent value was supplied" in info.note

    def test_ignores_context_for_parents_this_param_does_not_have(self) -> None:
        info = format_typed_param(
            _samples("samples_percentile_generic"),
            self._DEPENDS,
            {},
            applied_context={"organism": SinglePickValue(value="P. falciparum")},
        )

        assert info.note is not None
        assert "No parent value was supplied" in info.note


class TestAnUnqualifiedRead:
    """A vocabulary read without parents names the defaults it was read under."""

    _DEPENDS: ClassVar[dict[str, list[str]]] = {"samples": ["profileset"]}

    def _default_note(self) -> str:
        info = format_typed_param(
            _samples("samples"),
            self._DEPENDS,
            {},
            parent_defaults={"profileset": "DeRisi HB3 Smoothed"},
        )
        assert info.note is not None
        return info.note

    def test_the_note_names_the_parent_value_wdk_used(self) -> None:
        assert "DeRisi HB3 Smoothed" in self._default_note()

    def test_it_warns_that_another_parent_gives_another_list(self) -> None:
        assert "DIFFERENT" in self._default_note()

    def test_without_a_known_default_it_still_says_it_is_a_default(self) -> None:
        info = format_typed_param(_samples("samples"), self._DEPENDS, {})

        assert info.note is not None
        assert "default" in info.note.lower()

    def test_an_applied_context_still_names_what_was_applied(self) -> None:
        info = format_typed_param(
            _samples("samples"),
            self._DEPENDS,
            {},
            applied_context={
                "profileset": SinglePickValue(value="DeRisi 3D7 Smoothed")
            },
            parent_defaults={"profileset": "DeRisi HB3 Smoothed"},
        )

        assert info.note is not None
        assert "DeRisi 3D7 Smoothed" in info.note
        assert "DeRisi HB3 Smoothed" not in info.note


class TestRequiredFollowsBothWdkSignals:
    """WDK marks a parameter mandatory with allowEmptyValue or minSelectedCount."""

    @staticmethod
    def _required(*, allow_empty: bool, min_selected: int) -> bool:
        param = WDKEnumParam.model_validate(
            {
                "name": "organism",
                "type": "multi-pick-vocabulary",
                "allowEmptyValue": allow_empty,
                "minSelectedCount": min_selected,
            }
        )
        return format_typed_param(param, {}, {}).required

    def test_a_minimum_selection_makes_a_param_required(self) -> None:
        assert self._required(allow_empty=True, min_selected=1) is True

    def test_an_empty_value_is_allowed_when_nothing_must_be_selected(self) -> None:
        assert self._required(allow_empty=True, min_selected=0) is False

    def test_forbidding_an_empty_value_is_enough_on_its_own(self) -> None:
        assert self._required(allow_empty=False, min_selected=0) is True


class TestThePhyleticListsCarryTheTree:
    """``GenesByOrthologPattern`` states its criterion on two free-text lists.

    The lists are the proposal, so the sheet must show the vocabulary they take.
    """

    @staticmethod
    def _params(*, with_term_map: bool = True) -> list[WDKParameter]:
        params: list[WDKParameter] = [
            WDKStringParam(
                name="profile_pattern",
                display_name="Phyletic Pattern",
                is_visible=False,
                initial_display_value="hsap=1T",
            ),
            WDKStringParam(
                name="included_species",
                display_name="Included Species",
                help="For documentation only.",
                allow_empty_value=True,
                initial_display_value="",
            ),
            WDKStringParam(
                name="excluded_species",
                display_name="Excluded Species",
                allow_empty_value=True,
                initial_display_value="",
            ),
            WDKEnumParam(
                name="phyletic_indent_map",
                display_name="Indent Map",
                type="multi-pick-vocabulary",
                vocabulary=_PHYLETIC_INDENTS,
            ),
            WDKEnumParam(
                name="organism",
                display_name="Organism",
                type="multi-pick-vocabulary",
                vocabulary=_one_leaf_tree("P. falciparum 3D7"),
            ),
        ]
        if with_term_map:
            params.append(
                WDKEnumParam(
                    name="phyletic_term_map",
                    display_name="Term Map",
                    type="multi-pick-vocabulary",
                    vocabulary=_PHYLETIC_TERMS,
                )
            )
        return params

    @classmethod
    def _sheet(cls, *, with_term_map: bool = True) -> dict[str, ParameterInfo]:
        infos = format_param_info_typed(cls._params(with_term_map=with_term_map))
        return {info.name: info for info in infos}

    def test_both_lists_take_the_species_and_clade_codes(self) -> None:
        sheet = self._sheet()

        for name in ("included_species", "excluded_species"):
            codes = [option.value for option in sheet[name].vocabulary()]
            assert "pfal" in codes
            assert "MAMM" in codes

    def test_the_synthetic_root_is_not_a_choice(self) -> None:
        sheet = self._sheet()

        assert all(o.value != "ALL" for o in sheet["included_species"].vocabulary())

    def test_the_codes_carry_their_species_names(self) -> None:
        options = {
            o.value: o.display for o in self._sheet()["excluded_species"].vocabulary()
        }

        assert options["hsap"] == "Homo sapiens REF"

    def test_the_help_ends_by_naming_the_derivation(self) -> None:
        sheet = self._sheet()

        assert sheet["included_species"].help.endswith(_PHYLETIC_HELP_SENTENCE)
        assert sheet["included_species"].help.startswith("For documentation only.")
        assert sheet["excluded_species"].help == _PHYLETIC_HELP_SENTENCE

    def test_the_codes_reach_the_wire_through_allowed_values(self) -> None:
        # ``vocab_leaves`` is excluded from serialization, so a tool result that
        # sends only ``allowed_values`` would show the model an empty vocabulary.
        allowed = self._sheet()["included_species"].allowed_values

        assert allowed is not None
        assert [o.value for o in allowed] == ["EUKA", "MAMM", "hsap", "pfal"]

    def test_the_lists_are_optional_the_way_wdk_declares_them(self) -> None:
        assert self._sheet()["included_species"].required is False
        assert self._sheet()["included_species"].default_value == ""

    def test_the_pattern_stays_off_the_visible_sheet(self) -> None:
        assert self._sheet()["profile_pattern"].is_visible is False

    def test_the_two_maps_are_dropped(self) -> None:
        sheet = self._sheet()

        assert "phyletic_term_map" not in sheet
        assert "phyletic_indent_map" not in sheet

    def test_another_search_leaves_the_lists_alone(self) -> None:
        sheet = self._sheet(with_term_map=False)

        assert sheet["included_species"].vocabulary() == []
        assert sheet["included_species"].help == "For documentation only."

    def test_the_other_params_keep_their_own_vocabulary(self) -> None:
        codes = [o.value for o in self._sheet()["organism"].vocabulary()]

        assert codes == ["root", "P. falciparum 3D7"]


class TestTheFullTreeSurvivesTheWireCap:
    """The live tree is hundreds of nodes. The wire view is capped; matching is not."""

    _LEAF_COUNT = _MAX_VOCAB_ENTRIES + 11

    @classmethod
    def _big_sheet(cls) -> ParameterInfo:
        terms = vocab_terms(("ALL", "Root"), ("EUKA", "Eukaryota"))
        indents = vocab_terms(("EUKA", "1"))
        for i in range(cls._LEAF_COUNT):
            terms += vocab_terms((f"sp{i:02d}", f"Species {i}"))
            indents += vocab_terms((f"sp{i:02d}", "2"))
        params: list[WDKParameter] = [
            WDKStringParam(name="profile_pattern", is_visible=False),
            WDKStringParam(name="included_species", allow_empty_value=True),
            WDKStringParam(name="excluded_species", allow_empty_value=True),
            WDKEnumParam(
                name="phyletic_term_map",
                type="multi-pick-vocabulary",
                vocabulary=terms,
            ),
            WDKEnumParam(
                name="phyletic_indent_map",
                type="multi-pick-vocabulary",
                vocabulary=indents,
            ),
        ]
        infos = {info.name: info for info in format_param_info_typed(params)}
        return infos["included_species"]

    def test_the_wire_view_is_capped(self) -> None:
        allowed = self._big_sheet().allowed_values

        assert allowed is not None
        assert len(allowed) == _MAX_VOCAB_ENTRIES

    def test_the_note_says_the_list_was_truncated(self) -> None:
        note = self._big_sheet().allowed_values_note

        assert note is not None
        assert str(_MAX_VOCAB_ENTRIES) in note

    def test_matching_still_sees_every_node(self) -> None:
        # The clade plus every species, uncapped, so a value the cap hid still binds.
        assert len(self._big_sheet().vocabulary()) == self._LEAF_COUNT + 1


class TestFormatNormalizedParamInfo:
    def test_it_emits_vocab_and_dependency_links(self) -> None:
        specs: dict[str, ParamSpecNormalized] = {
            "organism": ParamSpecNormalized(
                name="organism",
                param_type="single-pick-vocabulary",
                allow_empty_value=False,
                vocabulary=vocab_terms(
                    ("Pf3D7", "P. falciparum 3D7"), ("PvP01", "P. vivax P01")
                ),
                dependent_params=("taxon",),
            ),
            "taxon": ParamSpecNormalized(
                name="taxon",
                param_type="single-pick-vocabulary",
                allow_empty_value=False,
                vocabulary=vocab_terms(
                    ("PfTaxonA", "Pf Taxon A"), ("PfTaxonB", "Pf Taxon B")
                ),
            ),
        }

        by_name = {p.name: p for p in format_normalized_param_info(specs)}

        assert by_name["organism"].required is True
        assert by_name["organism"].controls_vocab_of == ["taxon"]
        assert by_name["organism"].vocab_depends_on is None
        taxon = by_name["taxon"]
        assert taxon.vocab_depends_on == ["organism"]
        assert taxon.allowed_values is not None
        assert sorted(v.value for v in taxon.allowed_values) == ["PfTaxonA", "PfTaxonB"]

    def test_it_truncates_a_large_vocab(self) -> None:
        huge = [WDKVocabTerm((f"v{i}", f"v{i}", None)) for i in range(200)]
        specs = {
            "p": ParamSpecNormalized(
                name="p", param_type="single-pick-vocabulary", vocabulary=huge
            )
        }

        formatted = format_normalized_param_info(specs)

        assert formatted[0].allowed_values is not None
        assert len(formatted[0].allowed_values) == 50
        assert formatted[0].allowed_values_note is not None
        assert "truncated" in formatted[0].allowed_values_note.lower()
