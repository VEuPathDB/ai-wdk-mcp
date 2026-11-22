from __future__ import annotations

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain.parameters import (
    FilterValue,
    HeldValue,
    MultiPickValue,
    ParamValue,
    shown_stated,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording

from veupathdb_mcp.catalog import (
    MovedParentError,
    read_under_parents,
)
from veupathdb_mcp.catalog.facet_ranges import EmptyRangeError

from .conftest import serving
from .test_a_filter_statement_binds_by_its_facet import (
    ngs_snps,
    variant_characteristics,
)

_PF = "Plasmodium falciparum 3D7"
_PCHA = "Plasmodium chabaudi chabaudi"
_PREI = "Plasmodium reichenowi CDC"
_PAST_THE_RANGE = FilterValue.model_validate(
    {
        "filters": [
            {
                "field": "total_variants",
                "type": "number",
                "isRange": True,
                "includeUnknown": False,
                "value": {"min": 4824},
            }
        ]
    }
)
_HELD: dict[str, ParamValue] = {
    "organism_select_none": MultiPickValue(values=[_PF]),
    "gene_variant_stats": _PAST_THE_RANGE,
}

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)


async def _read(stated: dict[str, JsonValue]) -> dict[str, ParamValue]:
    return dict(
        await read_under_parents(
            serving(*variant_characteristics()),
            stated,
            FilterReadsDouble(
                {"total_variants": "ontology_term_summary_total_variants"}
            ),
            about=None,
            bound=_HELD,
        )
    )


async def test_a_child_given_back_under_its_held_parent_is_the_held_value() -> None:
    read = await _read(
        {
            "organism_select_none": [_PF],
            "gene_variant_stats": shown_stated(_PAST_THE_RANGE),
        }
    )

    assert read == _HELD


_MOVED = (
    'organism_select_none moved from ["Plasmodium falciparum 3D7"] to '
    '["Plasmodium chabaudi chabaudi"], so gene_variant_stats, which held '
    '[{"field": "total_variants", "value": {"min": 4824.0}}], was read again '
    "under it and refused: "
)
_ASK = (
    " State gene_variant_stats again under the new organism_select_none, or leave "
    "it out if a reader can keep it."
)


@pytest.mark.parametrize(
    "stated",
    [
        {
            "organism_select_none": [_PCHA],
            "gene_variant_stats": shown_stated(_PAST_THE_RANGE),
        },
        {"organism_select_none": [_PCHA]},
    ],
)
async def test_a_child_under_a_new_parent_is_read_again_and_refused_in_words(
    stated: dict[str, JsonValue],
) -> None:
    with pytest.raises(MovedParentError) as refused:
        await _read(stated)

    assert refused.value.child == "gene_variant_stats"
    assert refused.value.detail.startswith(_MOVED)
    assert "selects none of it" in refused.value.detail
    assert refused.value.detail.endswith(_ASK)


async def test_a_held_child_left_out_under_its_held_parent_is_not_read() -> None:
    assert await _read({"organism_select_none": [_PF]}) == {
        "organism_select_none": MultiPickValue(values=[_PF])
    }


async def test_a_kept_child_under_a_new_parent_is_offered_the_new_members() -> None:
    held = HeldValue(wire='{"filters":[{"field":"unknown"}]}')

    with pytest.raises(MovedParentError) as refused:
        await read_under_parents(
            serving(*ngs_snps()),
            {"organismSinglePick": [_PREI]},
            FilterReadsDouble(),
            about=None,
            bound={
                "organismSinglePick": MultiPickValue(values=[_PF]),
                "variation_sample_meta": held,
            },
        )

    detail = refused.value.detail
    offered = detail.split(" offers: ", 1)[1].split(". State ", 1)[0]
    assert offered.split("; ") == [
        "Dataset",
        "Sample name",
        "age",
        "Collection date as provided",
        "Collection site",
    ]
    assert len(detail) < 2000
    assert detail.startswith(
        f'organismSinglePick moved from ["{_PF}"] to ["{_PREI}"], so '
        f"variation_sample_meta, which held '{held.wire}' (kept as the site holds "
        "it), was read again under it and refused: variation_sample_meta takes "
    )
    assert "Under the new organismSinglePick, variation_sample_meta offers: " in detail


async def test_a_context_read_notes_a_stale_child_and_binds_nothing_for_it() -> None:
    noted: list[MovedParentError] = []
    read = await read_under_parents(
        serving(*variant_characteristics()),
        {"organism_select_none": [_PCHA]},
        FilterReadsDouble({"total_variants": "ontology_term_summary_total_variants"}),
        about=None,
        bound=_HELD,
        stale=noted,
    )

    assert read == {"organism_select_none": MultiPickValue(values=[_PCHA])}
    [stale] = noted
    assert stale.child == "gene_variant_stats"
    assert stale.detail.startswith(_MOVED)
    assert stale.detail.endswith(_ASK)


_KEPT = HeldValue(wire='{"filters":[{"field":"unknown"}]}')
_NGS_HELD: dict[str, ParamValue] = {
    "organismSinglePick": MultiPickValue(values=[_PF]),
    "variation_sample_meta": _KEPT,
}


_ORGANISM = {"organismSinglePick": MultiPickValue(values=[_PF])}


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        ({"organismSinglePick": [_PF.lower()]}, _ORGANISM),
        (
            {"organismSinglePick": [_PF.lower()], "variation_sample_meta": _KEPT.wire},
            {**_ORGANISM, "variation_sample_meta": _KEPT},
        ),
    ],
)
async def test_a_parent_restated_in_another_form_moves_no_child(
    stated: dict[str, JsonValue], expected: dict[str, ParamValue]
) -> None:
    read = await read_under_parents(
        serving(*ngs_snps()), stated, FilterReadsDouble(), about=None, bound=_NGS_HELD
    )

    assert read == expected


async def test_a_multi_pick_parent_restated_in_another_order_moves_no_child() -> None:
    held: dict[str, ParamValue] = {
        "organism_select_none": MultiPickValue(values=[_PF, _PCHA]),
        "gene_variant_stats": _KEPT,
    }

    read = await read_under_parents(
        serving(*variant_characteristics()),
        {"organism_select_none": [_PCHA, _PF]},
        FilterReadsDouble(),
        about=None,
        bound=held,
    )

    assert read == {"organism_select_none": MultiPickValue(values=[_PCHA, _PF])}


_OUT_OF_REACH: JsonValue = [{"field": "total_variants", "value": {"min": 99999999}}]


async def test_a_child_stated_anew_under_a_moved_parent_is_refused_as_stated() -> None:
    with pytest.raises(EmptyRangeError) as refused:
        await _read(
            {"organism_select_none": [_PCHA], "gene_variant_stats": _OUT_OF_REACH}
        )

    assert '{"min": 99999999} selects none of it' in refused.value.detail


async def test_a_context_read_refuses_a_child_it_states_anew() -> None:
    with pytest.raises(EmptyRangeError):
        await read_under_parents(
            serving(*variant_characteristics()),
            {"organism_select_none": [_PCHA], "gene_variant_stats": _OUT_OF_REACH},
            FilterReadsDouble(
                {"total_variants": "ontology_term_summary_total_variants"}
            ),
            about=None,
            bound=_HELD,
            stale=[],
        )


async def test_each_clause_of_a_held_filter_is_offered_its_own_members() -> None:
    held = FilterValue.model_validate(
        {
            "filters": [
                {
                    "field": "VAR_8e68b3e5",
                    "type": "string",
                    "isRange": False,
                    "includeUnknown": False,
                    "value": ["Peru"],
                },
                {
                    "field": "VAR_68bb04bd",
                    "type": "string",
                    "isRange": False,
                    "includeUnknown": False,
                    "value": ["female"],
                },
            ]
        }
    )

    with pytest.raises(MovedParentError) as refused:
        await read_under_parents(
            serving(*ngs_snps()),
            {"organismSinglePick": [_PREI]},
            FilterReadsDouble(),
            about=None,
            bound={**_ORGANISM, "variation_sample_meta": held},
        )

    offered = refused.value.detail.split(" offers: ", 1)[1].split(". State ", 1)[0]
    assert offered.split("; ") == ["sex: female", "sex: male"]
