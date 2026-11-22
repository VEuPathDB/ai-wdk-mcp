from __future__ import annotations

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain.parameters import (
    HeldValue,
    MultiPickValue,
    StatedValuesError,
    shown_stated,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog import read_under_parents

_SNPS = "search_genes_by_ngs_snps"
_PF = "Plasmodium falciparum 3D7"
_HELD = HeldValue(wire='{"filters":[{"field":"unknown"}]}')
pytestmark = pytest.mark.skipif(
    needs_qa_recording(f"wdk/{_SNPS}.json"), reason=NEEDS_QA_RECORDING
)


async def _fetch_at(context: dict[str, str]) -> list[WDKParameter]:
    del context
    search = WDKSearchResponse.model_validate(load_recorded(_SNPS).json_body())
    return search.search_data.parameters or []


async def _read(given: JsonValue) -> dict[str, object]:
    return dict(
        await read_under_parents(
            _fetch_at,
            {"organismSinglePick": [_PF], "variation_sample_meta": given},
            FilterReadsDouble(),
            about=None,
            bound={"variation_sample_meta": _HELD},
        )
    )


@pytest.mark.parametrize("given", [shown_stated(_HELD), _HELD.wire])
async def test_a_kept_value_given_back_is_the_held_value(given: JsonValue) -> None:
    read = await _read(given)

    assert read == {
        "organismSinglePick": MultiPickValue(values=[_PF]),
        "variation_sample_meta": _HELD,
    }


async def test_a_kept_text_with_no_held_value_is_refused() -> None:
    with pytest.raises(StatedValuesError):
        await read_under_parents(
            _fetch_at,
            {"variation_sample_meta": shown_stated(_HELD)},
            FilterReadsDouble(),
            about=None,
        )
