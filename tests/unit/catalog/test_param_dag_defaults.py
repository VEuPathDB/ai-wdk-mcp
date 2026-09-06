"""What binds when the request states no override: defaults, quantities, examples.

The walk reads no English. A default is legitimate when the request says nothing
about the value; a visible free-text default is an example in the form, and a
quantity the request states must bind or come back to be read.
"""

from __future__ import annotations

import json

import pytest
from veupathdb.domain.parameters.value_codec import to_wire
from veupathdb.domain.parameters.values import (
    MultiPickValue,
    SinglePickValue,
    StringValue,
)
from veupathdb.domain.parameters.wdk_vocab import VocabOption

from veupathdb_mcp.catalog.param_dag import (
    OverrideMap,
    ParameterInfo,
    ParamFetcher,
    ResolvedParams,
    resolve_params_with_intent,
)
from veupathdb_mcp.catalog.param_intent import ParamIntent, Provenance

from .conftest import fetcher, param_info, vocab

_PCT = "min_expression_percentile"
_STAGES = vocab("ring", "trophozoite")
_HOURS = [f"{h} Hour" for h in range(1, 49)]
_TROPHOZOITE = [f"{h} Hour" for h in range(20, 33)]
_TEXT_FIELDS = [
    "apolloCommentContent",
    "ECNumbers",
    "Epitopes",
    "GeneLinkouts",
    "product",
    "Products",
    "name",
    "Notes",
]
_PF = "Plasmodium falciparum 3D7"
_PV = "Plasmodium vivax P01"


def _numeric(name: str, default: str = "80", *, required: bool = True) -> ParameterInfo:
    return param_info(
        name, "string", is_number=True, required=required, default=default
    )


def _text(name: str, default: str = "") -> ParameterInfo:
    return param_info(name, "string", default=default)


async def _resolve(
    text: str, *infos: ParameterInfo, overrides: OverrideMap | None = None
) -> ResolvedParams:
    return await resolve_params_with_intent(
        fetch_at=fetcher(*infos), intent=ParamIntent(text=text), overrides=overrides
    )


class TestTheWalkDisclosesWhatItDefaulted:
    async def test_a_vocabulary_param_is_a_default_or_a_slot(self) -> None:
        defaulted = await _resolve(
            "trophozoite stage", param_info("stage", allowed=_STAGES, default="ring")
        )
        assert defaulted.provenance["stage"] is Provenance.DEFAULTED

        asked = await _resolve(
            "trophozoite stage", param_info("stage", allowed=_STAGES)
        )
        assert [s.param_name for s in asked.open_slots] == ["stage"]

    async def test_an_override_binds_as_stated(self) -> None:
        resolved = await _resolve(
            "", param_info("stage", allowed=_STAGES), overrides={"stage": "trophozoite"}
        )

        assert resolved.provenance["stage"] is Provenance.STATED

    async def test_a_defaulted_param_is_listed(self) -> None:
        resolved = await _resolve(
            "anything", param_info("stage", allowed=_STAGES, default="ring")
        )

        assert resolved.defaulted() == ["stage"]

    async def test_a_stated_param_is_not_listed(self) -> None:
        resolved = await _resolve(
            "anything",
            param_info("stage", allowed=_STAGES),
            overrides={"stage": "ring"},
        )

        assert resolved.defaulted() == []


class TestAStatedQuantityIsReportedUnread:
    """Taking a default when the request states a quantity answers a question
    nobody asked and reports it as the user's intent."""

    async def test_a_stated_quantity_left_null_is_reported_not_defaulted(self) -> None:
        resolved = await _resolve("top 10 percent, so percentile 90", _numeric(_PCT))

        assert resolved.unread == [_PCT]
        assert _PCT not in resolved.params

    async def test_it_is_reported_unresolved_and_is_not_a_question(self) -> None:
        # An open slot asks the user. This asks the caller to read the request it
        # already has, so it must not reach the user as a question.
        resolved = await _resolve("top 10 percent", _numeric(_PCT))

        assert resolved.unresolved_required == [_PCT]
        assert resolved.open_slots == []
        assert resolved.defaulted() == []

    async def test_an_optional_param_is_reported_too(self) -> None:
        # An optional param dropped here runs on the search's own default anyway,
        # so silence would lose the stated number just as quietly.
        resolved = await _resolve("top 10 percent", _numeric(_PCT, required=False))

        assert resolved.unread == [_PCT]
        assert _PCT not in resolved.params

    @pytest.mark.parametrize(
        ("text", "name"),
        [
            ("top 10%", _PCT),
            ("adjusted p-value below 0.05", "adj_p_value"),
            ("dN/dS <= 1.3", "dn_ds_ratio_upper"),
            ("at least 2 peptides", "min_peptides"),
        ],
    )
    async def test_a_quantity_in_any_notation_is_read(
        self, text: str, name: str
    ) -> None:
        assert (await _resolve(text, _numeric(name))).unread == [name]


class TestTheStatedValueBinds:
    async def test_passing_the_value_leaves_nothing_unread(self) -> None:
        resolved = await _resolve(
            "top 10 percent, so percentile 90", _numeric(_PCT), overrides={_PCT: "90"}
        )

        assert resolved.unread == []
        assert to_wire(resolved.params[_PCT]) == "90"

    async def test_a_default_that_equals_the_stated_quantity_binds(self) -> None:
        resolved = await _resolve("percentile 90", _numeric(_PCT, "90"))

        assert resolved.unread == []
        assert to_wire(resolved.params[_PCT]) == "90"


class TestTheRequestStatesNoQuantity:
    @pytest.mark.parametrize(
        ("text", "name", "default"),
        [
            ("genes under purifying selection", "dn_ds_ratio_lower", "0"),
            ("", "dn_ds_ratio_lower", "0"),
            # An accession is an identifier. Reading it as a threshold would hold
            # the default back on every domain search.
            ("InterPro domain PF00069", "min_peptides", "80"),
            ("gene PF3D7_0100100", "min_peptides", "80"),
        ],
    )
    async def test_the_default_is_kept(
        self, text: str, name: str, default: str
    ) -> None:
        resolved = await _resolve(text, _numeric(name, default))

        assert resolved.unread == []
        assert to_wire(resolved.params[name]) == default


class TestSeveralNumericSlotsAreLeftAlone:
    """One number and several numeric params does not say which one it answers.

    Holding all of them back trades more correct defaults than it saves wrong
    ones, measured against the gold corpus.
    """

    async def test_two_unrelated_quantities_keep_their_defaults(self) -> None:
        resolved = await _resolve(
            "dN/dS <= 1.3",
            _numeric("dn_ds_ratio_lower", "0"),
            _numeric("snp_density_lower", "0"),
        )

        assert resolved.unread == []
        assert to_wire(resolved.params["dn_ds_ratio_lower"]) == "0"
        assert to_wire(resolved.params["snp_density_lower"]) == "0"

    async def test_a_numeric_slot_beside_a_text_param_is_still_held_back(self) -> None:
        resolved = await _resolve(
            "top 10 percent", _numeric(_PCT), _text("organism", "Plasmodium")
        )

        assert resolved.unread == [_PCT]

    async def test_a_sibling_with_no_default_does_not_count(self) -> None:
        resolved = await _resolve(
            "top 10 percent", _numeric(_PCT), _numeric("max_expression_percentile", "")
        )

        assert resolved.unread == [_PCT]


class TestOnlyNumericParamsAreAffected:
    async def test_a_text_param_is_never_held_back(self) -> None:
        # A free-text default is suppressed for its own reasons, and that opens a
        # slot for the user rather than reporting the param unread.
        resolved = await _resolve("top 10 percent", _text("text_expression", "kinase"))

        assert resolved.unread == []
        assert [slot.param_name for slot in resolved.open_slots] == ["text_expression"]

    async def test_a_numeric_param_with_no_default_is_a_question(self) -> None:
        resolved = await _resolve("top 10 percent", _numeric("min_peptides", ""))

        assert resolved.unread == []
        assert [slot.param_name for slot in resolved.open_slots] == ["min_peptides"]


def _genes_by_text() -> ParamFetcher:
    return fetcher(
        param_info(
            "text_search_organism",
            "multi-pick-vocabulary",
            allowed=[],
            leaves=vocab("Aedes aegypti LVP_AGWG", "Anopheles gambiae PEST"),
            default="[]",
        ),
        param_info("text_expression", "string", default="*reductase"),
        param_info("document_type", "string", default="gene", visible=False),
        param_info(
            "text_fields",
            "multi-pick-vocabulary",
            allowed=vocab(*_TEXT_FIELDS),
            default=json.dumps(_TEXT_FIELDS),
        ),
    )


async def _resolve_text(overrides: OverrideMap | None = None) -> ResolvedParams:
    return await resolve_params_with_intent(
        fetch_at=_genes_by_text(), intent=ParamIntent(), overrides=overrides
    )


class TestFreeTextAndFullListDefaults:
    async def test_a_visible_free_text_param_is_never_bound_from_the_example(
        self,
    ) -> None:
        resolved = await _resolve_text()

        assert "text_expression" not in resolved.params, (
            "bound the WDK example value; an OBP search silently becomes a "
            f"reductase search: {resolved.params.get('text_expression')!r}"
        )
        assert any(s.param_name == "text_expression" for s in resolved.open_slots)

    async def test_a_hidden_string_param_keeps_its_default(self) -> None:
        """A hidden required string param is an internal switch, so its default
        holds."""
        resolved = await _resolve_text()

        value = resolved.params["document_type"]
        assert isinstance(value, StringValue)
        assert value.value == "gene"
        assert not any(s.param_name == "document_type" for s in resolved.open_slots)

    async def test_a_free_text_param_accepts_an_explicit_override(self) -> None:
        resolved = await _resolve_text({"text_expression": "odorant binding protein"})

        value = resolved.params["text_expression"]
        assert isinstance(value, StringValue)
        assert value.value == "odorant binding protein"
        assert not any(s.param_name == "text_expression" for s in resolved.open_slots)

    async def test_the_full_list_default_is_kept_whole(self) -> None:
        """The WDK default searches every field, and nothing narrows it unasked."""
        fields = (await _resolve_text()).params["text_fields"]

        assert isinstance(fields, MultiPickValue)
        assert fields.values == _TEXT_FIELDS, (
            f"curated field default narrowed to {fields.values}"
        )

    async def test_an_explicit_override_still_narrows_the_field_list(self) -> None:
        fields = (await _resolve_text({"text_fields": "product"})).params["text_fields"]

        assert isinstance(fields, MultiPickValue)
        assert fields.values == ["product"]

    async def test_an_open_slot_offers_the_tree_vocabulary(self) -> None:
        """A tree-box param keeps its values in the leaves, because the allowed
        list is empty."""
        resolved = await _resolve_text()

        slot = next(
            (s for s in resolved.open_slots if s.param_name == "text_search_organism"),
            None,
        )
        if slot is not None:
            assert slot.options, "asked 'choose a value' while offering no values"
            assert "Aedes aegypti LVP_AGWG" in slot.options


class TestAListOverrideStaysAList:
    """A multi-pick override serialized to WDK wire form before the walk reads it
    matches the vocabulary as ONE option and is then reported invalid."""

    @staticmethod
    async def _resolve_samples(override: str | list[str]) -> MultiPickValue:
        resolved = await resolve_params_with_intent(
            fetch_at=fetcher(
                param_info(
                    "samples_percentile_generic",
                    "multi-pick-vocabulary",
                    display_name="Samples",
                    leaves=vocab(*_HOURS),
                )
            ),
            intent=ParamIntent(),
            overrides={"samples_percentile_generic": override},
        )
        value = resolved.params["samples_percentile_generic"]
        assert isinstance(value, MultiPickValue)
        return value

    async def test_a_list_override_becomes_a_multi_pick_value(self) -> None:
        assert (await self._resolve_samples(_TROPHOZOITE)).values == _TROPHOZOITE

    async def test_it_does_not_collapse_the_list_into_one_option(self) -> None:
        value = await self._resolve_samples(_TROPHOZOITE)

        assert len(value.values) == len(_TROPHOZOITE), (
            "a serialized array counted as a single value, which is what WDK "
            "then rejected"
        )

    async def test_it_closes_the_open_slot(self) -> None:
        resolved = await resolve_params_with_intent(
            fetch_at=fetcher(
                param_info(
                    "samples_percentile_generic",
                    "multi-pick-vocabulary",
                    leaves=vocab(*_HOURS),
                )
            ),
            intent=ParamIntent(),
            overrides={"samples_percentile_generic": _TROPHOZOITE},
        )

        assert resolved.open_slots == []
        assert resolved.unresolved_required == []

    async def test_a_single_element_list_is_still_a_list(self) -> None:
        assert (await self._resolve_samples(["20 Hour"])).values == ["20 Hour"]

    async def test_a_scalar_override_still_resolves(self) -> None:
        assert (await self._resolve_samples("20 Hour")).values == ["20 Hour"]


_PF_PROFILESETS = vocab("DeRisi 3D7 Smoothed", "Su 3D7 strand-specific")
_PV_PROFILESETS = [VocabOption(value="Zhu P01 time course", display="Zhu P01")]


def _organism_param() -> ParameterInfo:
    return param_info(
        "organism",
        "multi-pick-vocabulary",
        display_name="Organism",
        leaves=[
            VocabOption(value=_PF, display="P. falciparum 3D7"),
            VocabOption(value=_PV, display="P. vivax P01"),
        ],
    )


def _profileset(options: list[VocabOption], default: str | None) -> ParameterInfo:
    return param_info(
        "profileset",
        display_name="Profile set",
        default=default,
        allowed=options,
        depends_on=["organism"],
    )


async def _under_organism(
    *, empty_under_vivax: bool, chosen: str
) -> tuple[dict[str, str], list[str]]:
    async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
        if _PV in context.get("organism", ""):
            options = [] if empty_under_vivax else _PV_PROFILESETS
            default = None if empty_under_vivax else "Zhu P01 time course"
            return [_organism_param(), _profileset(options, default)]
        return [_organism_param(), _profileset(_PF_PROFILESETS, "DeRisi 3D7 Smoothed")]

    resolved = await resolve_params_with_intent(
        fetch_at=fetch_at,
        intent=ParamIntent(text="expression profile of the protease genes"),
        overrides={"organism": [chosen]},
    )
    return (
        {name: to_wire(value) for name, value in resolved.params.items()},
        [slot.param_name for slot in resolved.open_slots],
    )


class TestSwappingTheParentReReadsItsDependents:
    """The dependent's vocabulary is only meaningful under its parents, so a
    substitution resolves the child at the new context."""

    async def test_the_dependent_is_read_under_the_new_parent(self) -> None:
        params, slots = await _under_organism(empty_under_vivax=False, chosen=_PV)

        assert params["profileset"] == "Zhu P01 time course"
        assert slots == []

    async def test_the_old_parents_default_is_not_carried_into_the_new_one(
        self,
    ) -> None:
        before, _ = await _under_organism(empty_under_vivax=False, chosen=_PF)
        after, _ = await _under_organism(empty_under_vivax=False, chosen=_PV)

        assert before["profileset"] == "DeRisi 3D7 Smoothed"
        assert after["profileset"] != before["profileset"]

    async def test_a_dependent_with_no_entry_under_the_new_parent_is_an_open_slot(
        self,
    ) -> None:
        """A parameter with nothing to choose is asked, never silently defaulted."""
        params, slots = await _under_organism(empty_under_vivax=True, chosen=_PV)

        assert "profileset" not in params
        assert slots == ["profileset"]

    async def test_the_untouched_parent_still_binds_what_the_request_states(
        self,
    ) -> None:
        params, _ = await _under_organism(empty_under_vivax=False, chosen=_PV)

        assert params["organism"] == '["Plasmodium vivax P01"]'
        assert (
            SinglePickValue(value="Zhu P01 time course").to_wire()
            == params["profileset"]
        )
