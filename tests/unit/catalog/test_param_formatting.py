"""Formatting WDK parameter specs into the info objects the model reads."""

from __future__ import annotations

from typing import ClassVar

from veupathdb.domain.parameters import (
    ParamValue,
    SinglePickValue,
    WDKFilterOntologyTerm,
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
)
from veupathdb.wdk import WDKEnumParam, WDKFilterParam, WDKParameter, WDKStringParam

from veupathdb_mcp.catalog.param_formatting import (
    _MAX_VOCAB_ENTRIES,
    ParamDependencies,
    ParameterInfo,
    format_param_info_typed,
    format_typed_param,
)

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

    info = format_typed_param(param, ParamDependencies())

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
    _APPLIED: ClassVar[dict[str, ParamValue]] = {
        "profileset_generic": SinglePickValue(value="DeRisi 3D7 Smoothed")
    }

    def _applied_note(self) -> str:
        info = format_typed_param(
            _samples("samples_percentile_generic"),
            ParamDependencies(depends_on=self._DEPENDS),
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
            _samples("samples_percentile_generic"),
            ParamDependencies(depends_on=self._DEPENDS),
        )

        assert info.note is not None
        assert "No parent value was supplied" in info.note

    def test_ignores_context_for_parents_this_param_does_not_have(self) -> None:
        info = format_typed_param(
            _samples("samples_percentile_generic"),
            ParamDependencies(depends_on=self._DEPENDS),
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
            ParamDependencies(depends_on=self._DEPENDS),
            parent_defaults={"profileset": "DeRisi HB3 Smoothed"},
        )
        assert info.note is not None
        return info.note

    def test_the_note_names_the_parent_value_wdk_used(self) -> None:
        assert "DeRisi HB3 Smoothed" in self._default_note()

    def test_it_warns_that_another_parent_gives_another_list(self) -> None:
        assert "DIFFERENT" in self._default_note()

    def test_without_a_known_default_it_still_says_it_is_a_default(self) -> None:
        info = format_typed_param(
            _samples("samples"), ParamDependencies(depends_on=self._DEPENDS)
        )

        assert info.note is not None
        assert "default" in info.note.lower()

    def test_an_applied_context_still_names_what_was_applied(self) -> None:
        info = format_typed_param(
            _samples("samples"),
            ParamDependencies(depends_on=self._DEPENDS),
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
        return format_typed_param(param, ParamDependencies()).required

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


class TestTheDependencyLinks:
    def test_a_parent_and_its_child_name_each_other(self) -> None:
        organism = WDKEnumParam(
            name="organism",
            display_name="Organism",
            type="single-pick-vocabulary",
            vocabulary=vocab_terms(
                ("Pf3D7", "P. falciparum 3D7"), ("PvP01", "P. vivax P01")
            ),
            dependent_params=["taxon"],
        )
        taxon = WDKEnumParam(
            name="taxon",
            display_name="Taxon",
            type="single-pick-vocabulary",
            vocabulary=vocab_terms(
                ("PfTaxonA", "Pf Taxon A"), ("PfTaxonB", "Pf Taxon B")
            ),
        )

        by_name = {p.name: p for p in format_param_info_typed([organism, taxon])}

        assert by_name["organism"].controls_vocab_of == ["taxon"]
        assert by_name["organism"].vocab_depends_on is None
        assert by_name["taxon"].vocab_depends_on == ["organism"]
        assert by_name["taxon"].allowed_values is not None
        assert sorted(v.value for v in by_name["taxon"].allowed_values) == [
            "PfTaxonA",
            "PfTaxonB",
        ]


class TestTheExpressionSheetStatesTheGrammarAndTheRecipes:
    @staticmethod
    def _help() -> str:
        return format_typed_param(
            WDKStringParam(
                name="phyletic_expression", help="Phyletic Pattern Expression"
            ),
            ParamDependencies(),
        ).help

    def test_a_count_with_t_counts_genomes_and_a_bare_count_counts_proteins(
        self,
    ) -> None:
        help_text = self._help()

        assert "'+'" in help_text
        assert "a count ending in T counts the genomes that hold a protein" in help_text
        assert "a bare count counts proteins over the listed genomes" in help_text
        assert "T counts taxa" not in help_text
        assert "lookup_phyletic_codes" in help_text

    def test_it_states_the_precedence_the_site_reads(self) -> None:
        help_text = self._help()

        assert (
            "The site drops parentheses and reads AND before OR, so write an OR of "
            "AND terms." in help_text
        )
        assert "parentheses state which binds first" not in help_text

    def test_two_or_conditions_in_one_and_term_multiply_out(self) -> None:
        assert (
            "Two OR conditions in one AND term multiply out into every pairing of "
            "their terms, each term repeating the shared units." in self._help()
        )

    def test_an_upper_bound_never_matches_an_absent_list(self) -> None:
        help_text = self._help()

        assert (
            "<, <= and >= count only groups with at least one protein in the list; "
            "write absence as L=0T." in help_text
        )
        assert "absence L=0T" in help_text
        assert "list<=(N-k)T" not in help_text

    def test_absence_from_k_repeats_the_other_units_of_its_and_term(self) -> None:
        help_text = self._help()

        assert "X AND L<=(N-k)T OR X AND L=0T" in help_text
        assert "with X the other units of the same AND term" in help_text
        assert "L<=(N-k)T OR L=0T when there are none" in help_text
        assert "X the rest of the expression" not in help_text

    def test_it_declares_no_length_limit(self) -> None:
        assert "The parameter declares no length limit." in self._help()

    def test_it_states_the_presence_recipes_over_a_list_of_n_genomes(self) -> None:
        help_text = self._help()

        assert "For a list L of N genomes: presence in every genome L=NT" in help_text
        assert "in at least p percent L>=ceil(pN/100)T" in help_text
        assert "in some but not all L>=1T AND L<NT" in help_text

    def test_a_species_is_present_when_at_least_half_its_genomes_are(self) -> None:
        help_text = self._help()

        assert "a species present when at least half its genomes are" in help_text
        assert "one unit S>=ceil(k/2)T per species S of k genomes" in help_text

    def test_single_copy_is_one_protein_in_every_genome(self) -> None:
        help_text = self._help()

        assert "Single copy, one protein in every genome: L=NT AND L=N" in help_text
        assert "no share or species form" in help_text

    def test_a_ratio_of_copy_numbers_is_a_sum_of_bands(self) -> None:
        help_text = self._help()

        assert "L1>=c*N1 AND L1<(c+1)*N1 AND L2>=r*c*N2" in help_text
        assert "the bands joined with OR" in help_text
        assert "c from 1 to the largest band the request asks" in help_text
        assert (
            "Band c selects the groups whose L2 protein total is at least r times c "
            "times N2 while the L1 total is from c times N1 up to below (c+1) times "
            "N1, so it compares list totals band by band, not each genome." in help_text
        )
        assert (
            "Band c=0, under N1 proteins in L1, is L1<N1 AND Y OR L1=0T AND Y, "
            "with Y the L2 condition; the second term keeps a group absent from L1, "
            "because < never matches a group with no protein in L1." in help_text
        )
        assert "average per genome" not in help_text
        assert "c=0 band is the absence form" not in help_text

    def test_one_genome_with_more_proteins_than_another_is_a_ladder(self) -> None:
        assert (
            "Genome A has more proteins than genome B: B=0 AND A>=1 OR B=1 AND A>=2 "
            "OR ... OR B=K AND A>=K+1, where K is the smallest count for which "
            "B>=K+1 returns no group; it is exact for two single genomes."
            in self._help()
        )

    def test_the_example_writes_absence_as_two_and_terms(self) -> None:
        help_text = self._help()

        assert (
            "present in genomes a and b and absent from at least 3 of genomes c, d, e "
            "and f: a+b=2T AND c+d+e+f<=1T OR a+b=2T AND c+d+e+f=0T" in help_text
        )
        assert "b+c+d" not in help_text
