from __future__ import annotations

import pytest
from tests._support.filter_reads import FilterReadsDouble
from tests._support.recorded_searches import recorded_search
from veupathdb.domain.parameters import HeldValue, ParamValue
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog import read_under_parents

pytestmark = pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_ngs_snps.json",
        "wdk/search_genes_by_ngs_snps_under_another_organism.json",
    ),
    reason=NEEDS_QA_RECORDING,
)

VIVAX = "Plasmodium vivax P01"
_KEPT = HeldValue(wire='{"filters":[{"field":"unknown"}]}')


async def _under(context: dict[str, str]) -> list[WDKParameter]:
    name = (
        "search_genes_by_ngs_snps_under_another_organism"
        if VIVAX in context.get("organismSinglePick", "")
        else "search_genes_by_ngs_snps"
    )
    return recorded_search(name).search_data.parameters or []


async def test_a_held_parent_restated_in_another_writing_keeps_its_child() -> None:
    bound: dict[str, ParamValue] = {
        "organismSinglePick": HeldValue(wire=f'[ "{VIVAX}" ]'),
        "variation_sample_meta": _KEPT,
    }

    read = await read_under_parents(
        _under,
        {"organismSinglePick": [VIVAX]},
        FilterReadsDouble(),
        about=None,
        bound=bound,
    )

    assert "variation_sample_meta" not in read
