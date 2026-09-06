"""Same-vocabulary sibling resolution: the degenerate-pair rule and contrast sides.

Two selectors drawn from one vocabulary that take one value compare a group to
itself. ``regulated_dir`` states the direction relative to the comparator.
"""

from __future__ import annotations

from collections.abc import Mapping

from veupathdb.domain.parameters.values import ParamValue
from veupathdb.domain.parameters.wdk_vocab import VocabOption

from veupathdb_mcp.catalog.param_dag import (
    OverrideMap,
    ParameterInfo,
    ParamFetcher,
    ResolvedParams,
    resolve_params_with_intent,
)
from veupathdb_mcp.catalog.param_intent import ParamIntent

from .conftest import bound, fetcher, param_info, vocab

MALE = VocabOption(value="male", display="male")
FEMALE = VocabOption(value="female", display="female")
SEXES = [MALE, FEMALE]
AVERAGE_ONLY = vocab("average1")
GROUPS = [
    VocabOption(value="g1", display="Group 1"),
    VocabOption(value="g2", display="Group 2"),
]
THREE = vocab("a", "b", "c")
# Verified against VectorBase GSE22339; "up" is a substring of the both option.
DIRECTIONS = vocab("down-regulated", "up or down regulated", "up-regulated")


def _assert_distinct(params: Mapping[str, ParamValue], a: str, b: str) -> None:
    if a in params and b in params:
        assert bound(params[a]) != bound(params[b]), f"degenerate pair on {a}, {b}"


async def _resolve(
    fetch_at: ParamFetcher, overrides: OverrideMap | None = None
) -> ResolvedParams:
    return await resolve_params_with_intent(
        fetch_at=fetch_at, intent=ParamIntent(), overrides=overrides
    )


class TestVocabularyPairs:
    async def test_a_shared_default_is_not_duplicated_into_a_degenerate_pair(
        self,
    ) -> None:
        pair = fetcher(
            param_info("samples_de_ref", allowed=GROUPS, default="g1"),
            param_info("samples_de_comp", allowed=GROUPS, default="g1"),
        )

        resolved = await _resolve(pair)

        # WDK measures the comparator against the reference, so the comparator
        # takes the default and the reference becomes the open question.
        assert bound(resolved.params["samples_de_comp"]) == ["g1"]
        assert "samples_de_ref" not in resolved.params
        assert any(s.param_name == "samples_de_ref" for s in resolved.open_slots)

    async def test_a_shared_override_is_not_duplicated_into_a_degenerate_pair(
        self,
    ) -> None:
        pair = fetcher(
            param_info("samples_de_ref_generic_deseq", allowed=GROUPS),
            param_info("samples_de_comp_generic_deseq", allowed=GROUPS),
        )

        resolved = await _resolve(pair, {"samples_de_comp_generic_deseq": "g1"})

        # The stated group binds the comparator, and the remaining group becomes
        # the reference.
        assert bound(resolved.params["samples_de_comp_generic_deseq"]) == ["g1"]
        assert bound(resolved.params["samples_de_ref_generic_deseq"]) == ["g2"]
        assert resolved.open_slots == []

    async def test_a_user_override_outranks_the_degenerate_pair_guard(self) -> None:
        pair = fetcher(
            param_info("samples_de_ref", allowed=GROUPS, default="g1"),
            param_info("samples_de_comp", allowed=GROUPS, default="g1"),
        )

        resolved = await _resolve(pair, {"samples_de_comp": "g1"})

        assert bound(resolved.params["samples_de_comp"]) == ["g1"]
        assert resolved.open_slots == []
        assert resolved.unresolved_required == []

    async def test_distinct_vocabularies_both_keep_their_defaults(self) -> None:
        # The same-value guard applies to one shared vocabulary only.
        resolved = await _resolve(
            fetcher(
                param_info("go_slim", allowed=vocab("No", "Yes"), default="No"),
                param_info(
                    "regulated_dir",
                    allowed=[
                        VocabOption(value="up", display="Up"),
                        VocabOption(value="down", display="Down"),
                    ],
                    default="up",
                ),
            )
        )

        assert bound(resolved.params["go_slim"]) == ["No"]
        assert bound(resolved.params["regulated_dir"]) == ["up"]
        assert resolved.open_slots == []

    async def test_a_one_option_vocabulary_binds_both_sides(self) -> None:
        # A one-option vocabulary leaves no second value, so both selectors bind
        # it and neither opens a slot.
        resolved = await _resolve(
            fetcher(
                param_info("min_max_avg_ref", allowed=AVERAGE_ONLY, default="average1"),
                param_info(
                    "min_max_avg_comp", allowed=AVERAGE_ONLY, default="average1"
                ),
            )
        )

        assert bound(resolved.params["min_max_avg_ref"]) == ["average1"]
        assert bound(resolved.params["min_max_avg_comp"]) == ["average1"]
        assert resolved.open_slots == []
        assert resolved.unresolved_required == []

    async def test_an_override_claims_its_value_before_siblings_auto_resolve(
        self,
    ) -> None:
        pair = fetcher(
            param_info(
                "samples_fc_ref_generic", "multi-pick-vocabulary", allowed=SEXES
            ),
            param_info(
                "samples_fc_comp_generic", "multi-pick-vocabulary", allowed=SEXES
            ),
        )

        resolved = await _resolve(pair, {"samples_fc_comp_generic": "female"})

        ref = bound(resolved.params["samples_fc_ref_generic"])
        comp = bound(resolved.params["samples_fc_comp_generic"])
        assert comp == ["female"], "the explicit override must be honored"
        assert ref != comp, f"degenerate self-comparison: ref and comp both {ref}"
        assert resolved.open_slots == []


def _vectorbase_microarray_fetch() -> ParamFetcher:
    """A fold-change search shape with a deferred dependent selector.

    ``samples_fc_comp_generic`` depends on ``profileset``, so it resolves in a
    later pass and its vocabulary is narrower until the parent binds.
    """

    async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
        resolved_parent = "profileset" in context
        return [
            param_info(
                "profileset",
                allowed=[VocabOption(value="ps1", display="Profile Set 1")],
            ),
            param_info(
                "samples_fc_ref_generic", "multi-pick-vocabulary", allowed=SEXES
            ),
            param_info(
                "samples_fc_comp_generic",
                "multi-pick-vocabulary",
                allowed=SEXES if resolved_parent else [FEMALE],
                depends_on=["profileset"],
            ),
            param_info("min_max_avg_ref", allowed=AVERAGE_ONLY, default="average1"),
            param_info(
                "min_max_avg_comp",
                allowed=AVERAGE_ONLY,
                default="average1",
                depends_on=["profileset"],
            ),
        ]

    return fetch_at


class TestADeferredSelector:
    async def test_single_option_operation_pair_binds_even_when_deferred(self) -> None:
        """A param with one legal value binds from its default, even when
        deferred, and never becomes an open slot."""
        resolved = await _resolve(_vectorbase_microarray_fetch())

        assert bound(resolved.params["min_max_avg_ref"]) == ["average1"]
        assert bound(resolved.params["min_max_avg_comp"]) == ["average1"]
        assert not any(
            s.param_name.startswith("min_max_avg") for s in resolved.open_slots
        )

    async def test_a_deferred_override_leaves_the_reference_the_other_group(
        self,
    ) -> None:
        resolved = await _resolve(
            _vectorbase_microarray_fetch(), {"samples_fc_comp_generic": "female"}
        )

        assert bound(resolved.params["samples_fc_comp_generic"]) == ["female"]
        assert bound(resolved.params["samples_fc_ref_generic"]) == ["male"]
        _assert_distinct(
            resolved.params, "samples_fc_ref_generic", "samples_fc_comp_generic"
        )
        assert resolved.open_slots == []

    async def test_both_selectors_pinned_is_honored_verbatim(self) -> None:
        resolved = await _resolve(
            _vectorbase_microarray_fetch(),
            {"samples_fc_ref_generic": "male", "samples_fc_comp_generic": "female"},
        )

        assert bound(resolved.params["samples_fc_ref_generic"]) == ["male"]
        assert bound(resolved.params["samples_fc_comp_generic"]) == ["female"]
        assert resolved.open_slots == []

    async def test_every_required_param_is_either_bound_or_asked_about(self) -> None:
        resolved = await _resolve(
            _vectorbase_microarray_fetch(), {"samples_fc_comp_generic": "female"}
        )

        accounted = set(resolved.params) | {s.param_name for s in resolved.open_slots}
        required = {
            "profileset",
            "samples_fc_ref_generic",
            "samples_fc_comp_generic",
            "min_max_avg_ref",
            "min_max_avg_comp",
        }
        assert required <= accounted, f"lost params: {sorted(required - accounted)}"


class TestEviction:
    async def test_an_override_evicts_a_default_across_a_deferred_dependency(
        self,
    ) -> None:
        """A deferred override reclaims the value a sibling default already took,
        and that sibling resolves again against what is left."""

        async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
            return [
                param_info(
                    "profileset",
                    allowed=[VocabOption(value="ps1", display="Profile Set 1")],
                ),
                param_info("stage_a", allowed=SEXES, default="female"),
                param_info(
                    "stage_b",
                    allowed=SEXES if "profileset" in context else [FEMALE],
                    depends_on=["profileset"],
                ),
            ]

        resolved = await _resolve(fetch_at, {"stage_b": "female"})

        assert bound(resolved.params["stage_b"]) == ["female"]
        assert bound(resolved.params["stage_a"]) == ["male"], (
            "the default kept the value the override claimed, so the pair is degenerate"
        )
        assert resolved.open_slots == []

    async def test_an_override_never_evicts_another_override(self) -> None:
        """Two explicit picks that collide are both honored."""
        pair = fetcher(
            param_info("ref", "multi-pick-vocabulary", allowed=SEXES),
            param_info("comp", "multi-pick-vocabulary", allowed=SEXES),
        )

        resolved = await _resolve(pair, {"ref": "female", "comp": "female"})

        assert bound(resolved.params["ref"]) == ["female"]
        assert bound(resolved.params["comp"]) == ["female"]

    async def test_eviction_asks_when_more_than_one_option_remains(self) -> None:
        """An evicted param with more than one remaining option becomes an open
        slot instead of a default."""
        pair = fetcher(
            param_info("ref", allowed=THREE, default="a"),
            param_info("comp", allowed=THREE, default="a"),
        )

        resolved = await _resolve(pair, {"comp": "a"})

        assert bound(resolved.params["comp"]) == ["a"]
        _assert_distinct(resolved.params, "ref", "comp")
        assert any(s.param_name == "ref" for s in resolved.open_slots)

    async def test_an_override_on_an_unrelated_vocabulary_evicts_nothing(self) -> None:
        resolved = await _resolve(
            fetcher(
                param_info("sex", allowed=SEXES, default="female"),
                param_info(
                    "direction",
                    allowed=[
                        VocabOption(value="up", display="Up"),
                        VocabOption(value="down", display="Down"),
                    ],
                    default="up",
                ),
            ),
            {"direction": "down"},
        )

        assert bound(resolved.params["sex"]) == ["female"], (
            "unrelated param must survive"
        )
        assert bound(resolved.params["direction"]) == ["down"]
        assert resolved.open_slots == []

    async def test_three_same_vocab_siblings_never_collide(self) -> None:
        """Eviction never leaves two same-vocabulary siblings on one value."""
        siblings = fetcher(
            *(
                param_info(name, allowed=THREE, default="a")
                for name in ("s1", "s2", "s3")
            )
        )

        resolved = await _resolve(siblings, {"s3": "a"})

        taken = {
            name: bound(value)
            for name, value in resolved.params.items()
            if name in {"s1", "s2", "s3"}
        }
        assert len(set(map(tuple, taken.values()))) == len(taken), (
            f"two siblings share a value: {taken}"
        )

    async def test_swapped_overrides_terminate_and_are_honored(self) -> None:
        """Overrides that each want the other's default settle without a repeated
        eviction loop."""
        pair = fetcher(
            param_info("ref", allowed=SEXES, default="male"),
            param_info("comp", allowed=SEXES, default="female"),
        )

        resolved = await _resolve(pair, {"ref": "female", "comp": "male"})

        assert bound(resolved.params["ref"]) == ["female"]
        assert bound(resolved.params["comp"]) == ["male"]

    async def test_aggregation_selectors_may_share_a_value(self) -> None:
        """An aggregation operation selects how to collapse replicates on one
        side, not which samples the side contains, so both sides may share a
        value."""
        ops = vocab("average1", "median2", "minimum2", "maximum2")
        pair = fetcher(
            param_info(
                "min_max_avg_ref",
                display_name="Operation Applied to Reference Samples",
                allowed=ops,
                default="average1",
            ),
            param_info(
                "min_max_avg_comp",
                display_name="Operation Applied to Comparison Samples",
                allowed=ops,
                default="average1",
            ),
        )

        resolved = await _resolve(pair)

        assert bound(resolved.params["min_max_avg_ref"]) == ["average1"]
        assert bound(resolved.params["min_max_avg_comp"]) == ["average1"]
        assert resolved.open_slots == []


def _fold_change_fetch() -> ParamFetcher:
    # Reference is listed FIRST, as WDK returns it.
    return fetcher(
        param_info(
            "samples_fc_ref_generic",
            "multi-pick-vocabulary",
            display_name="Reference Samples",
            allowed=SEXES,
        ),
        param_info(
            "samples_fc_comp_generic",
            "multi-pick-vocabulary",
            display_name="Comparison Samples",
            allowed=SEXES,
        ),
        param_info(
            "regulated_dir",
            display_name="Direction",
            allowed=DIRECTIONS,
            default="up or down regulated",
        ),
    )


class TestTheContrastDirection:
    """WDK states the rule in ``regulated_dir``'s help: up-regulated finds genes
    with higher expression in the COMPARATOR than in the REFERENCE."""

    async def test_the_baseline_becomes_the_group_the_comparator_did_not_take(
        self,
    ) -> None:
        resolved = await _resolve(
            _fold_change_fetch(), {"samples_fc_comp_generic": "female"}
        )

        comp = resolved.params.get("samples_fc_comp_generic")
        ref = resolved.params.get("samples_fc_ref_generic")
        assert comp is not None, "comparison slot left unbound"
        assert ref is not None, "reference slot left unbound"
        assert bound(comp) == ["female"]
        assert bound(ref) == ["male"]

    async def test_a_stated_direction_is_not_swallowed_by_the_both_option(self) -> None:
        """A substring of the both-directions label must not silently replace it."""
        resolved = await _resolve(
            _fold_change_fetch(),
            {"samples_fc_comp_generic": "female", "regulated_dir": "up-regulated"},
        )

        direction = resolved.params.get("regulated_dir")
        assert direction is not None
        assert bound(direction) == ["up-regulated"], (
            f"direction lost: bound {bound(direction)}"
        )

    async def test_no_stated_direction_keeps_the_wdk_both_directions_default(
        self,
    ) -> None:
        """Absent a statement, WDK's own default is the honest choice: inventing a
        direction would filter out half the answer without being asked to."""
        resolved = await _resolve(
            _fold_change_fetch(), {"samples_fc_comp_generic": "female"}
        )

        assert bound(resolved.params["regulated_dir"]) == ["up or down regulated"]

    async def test_both_sides_stated_are_honored_verbatim(self) -> None:
        resolved = await _resolve(
            _fold_change_fetch(),
            {"samples_fc_ref_generic": "female", "samples_fc_comp_generic": "male"},
        )

        assert bound(resolved.params["samples_fc_ref_generic"]) == ["female"]
        assert bound(resolved.params["samples_fc_comp_generic"]) == ["male"]

    async def test_the_pair_is_never_degenerate(self) -> None:
        resolved = await _resolve(
            _fold_change_fetch(), {"samples_fc_comp_generic": "female"}
        )

        ref = resolved.params.get("samples_fc_ref_generic")
        comp = resolved.params.get("samples_fc_comp_generic")
        if ref is not None and comp is not None:
            assert bound(ref) != bound(comp)

    async def test_an_unstated_pair_is_asked_about_rather_than_guessed(self) -> None:
        resolved = await _resolve(_fold_change_fetch())

        assert "samples_fc_comp_generic" not in resolved.params
        assert {s.param_name for s in resolved.open_slots} >= {
            "samples_fc_ref_generic",
            "samples_fc_comp_generic",
        }
