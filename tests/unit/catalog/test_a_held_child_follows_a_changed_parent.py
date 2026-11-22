from __future__ import annotations

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain.parameters import (
    FilterValue,
    MultiPickValue,
    ParamValue,
    shown_stated,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording

from veupathdb_mcp.catalog import read_under_parents
from veupathdb_mcp.catalog.facet_ranges import EmptyRangeError

from .conftest import serving
from .test_a_filter_statement_binds_by_its_facet import variant_characteristics

_PF = "Plasmodium falciparum 3D7"
_PCHA = "Plasmodium chabaudi chabaudi"
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


async def test_a_child_given_back_under_a_new_parent_is_read_again() -> None:
    with pytest.raises(EmptyRangeError):
        await _read(
            {
                "organism_select_none": [_PCHA],
                "gene_variant_stats": shown_stated(_PAST_THE_RANGE),
            }
        )


async def test_a_held_child_left_out_under_its_held_parent_is_not_read() -> None:
    assert await _read({"organism_select_none": [_PF]}) == {
        "organism_select_none": MultiPickValue(values=[_PF])
    }
