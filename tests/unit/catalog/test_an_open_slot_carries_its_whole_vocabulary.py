"""An open slot carries every entry of its vocabulary, read from recorded sheets."""

from __future__ import annotations

import pytest
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog._param_binding import _open_slot
from veupathdb_mcp.catalog._param_filters import _contrast_open_slot
from veupathdb_mcp.catalog.param_formatting import (
    ParameterInfo,
    format_param_info_typed,
)


def _recorded(name: str, param: str) -> ParameterInfo:
    body = load_recorded(name).json_body()
    infos = format_param_info_typed(
        WDKSearchResponse.model_validate(body).search_data.parameters or []
    )
    return next(info for info in infos if info.name == param)


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_exon_count.json"), reason=NEEDS_QA_RECORDING
)
def test_a_plasmodb_organism_slot_holds_every_organism() -> None:
    organism = _recorded("search_genes_by_exon_count", "organism")

    slot = _open_slot(organism)

    assert len(slot.options) == 90
    assert slot.options.index("Plasmodium falciparum 3D7") == 25


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_gene_model_chars.json"),
    reason=NEEDS_QA_RECORDING,
)
def test_a_vectorbase_organism_slot_holds_the_mosquitoes_after_the_ticks() -> None:
    organism = _recorded("search_genes_by_gene_model_chars", "organism_select_none")

    slot = _open_slot(organism)

    assert len(slot.options) == 189
    assert slot.options[:3] == ["Arthropoda", "Arachnida", "Ixodida"]
    assert slot.options.index("Anopheles gambiae PEST") == 113
    assert slot.options.index("Aedes aegypti LVP_AGWG") == 44


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)
def test_a_contrast_slot_holds_every_value_the_site_sent() -> None:
    samples = _recorded("search_genes_by_ngs_snps", "variation_sample_meta")
    reference = samples.model_copy(update={"name": "ref_samples"})

    slot = _contrast_open_slot(reference)

    assert len(slot.options) == 1521
    assert "VAR_8e68b3e5=Gambia" in slot.options
    assert "VAR_41eb2167=UGK_661.1" in slot.options
