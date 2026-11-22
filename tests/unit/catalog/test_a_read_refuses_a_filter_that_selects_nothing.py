"""The shared stated-value reader refuses a filter as the walk does."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKOntologyTermSummary

from veupathdb_mcp.catalog import (
    ResolveContext,
    ValidatedParams,
    facet_ranges,
    read_under_parents,
    search_inspection,
)
from veupathdb_mcp.catalog.discovery import CatalogPolicy, SearchCatalog
from veupathdb_mcp.catalog.facet_ranges import TooFewSelectedError
from veupathdb_mcp.tools import catalog_tools

from .conftest import serving
from .test_a_filter_statement_binds_by_its_facet import (
    ngs_snps,
    variant_characteristics,
)

_PF = ["Plasmodium falciparum 3D7"]

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)

_ABOUT = ResolveContext(site_id="plasmodb")


@pytest.fixture
def under_high_impact(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    summary = WDKOntologyTermSummary.model_validate(
        load_recorded(
            "ontology_term_summary_total_variants_under_high_impact"
        ).json_body()
    )
    client = MagicMock(get_ontology_term_summary=AsyncMock(return_value=summary))
    catalog = SearchCatalog(
        "plasmodb",
        cache_dir=Path("/nonexistent"),
        policy=CatalogPolicy(),
        spawn=MagicMock(),
    )
    service = MagicMock(get_catalog=AsyncMock(return_value=catalog))
    monkeypatch.setattr(facet_ranges, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(facet_ranges, "get_discovery_service", lambda: service)
    monkeypatch.setattr(
        search_inspection,
        "wdk_fetch_at",
        lambda *args: serving(*variant_characteristics()),
    )
    monkeypatch.setattr(
        catalog_tools,
        "validate_parameters",
        AsyncMock(return_value=ValidatedParams(params={}, record_class="transcript")),
    )
    return client


async def test_the_served_validation_refuses_a_range_empty_under_its_sibling(
    under_high_impact: MagicMock,
) -> None:
    with pytest.raises(ToolError, match="spans 2 to 4,823 variants over 3,207"):
        await catalog_tools.validate_search_parameters(
            "plasmodb",
            "GenesByVariantCharacteristics",
            {
                "organism_select_none": _PF,
                "gene_variant_stats": [
                    {"field": "most_severe_impact", "value": ["HIGH"]},
                    {"field": "total_variants", "value": {"max": 1}},
                ],
            },
            record_type="transcript",
        )

    under_high_impact.get_ontology_term_summary.assert_awaited_once()


async def test_a_read_refuses_a_selection_below_the_minimum() -> None:
    reads = FilterReadsDouble(count=1)

    with pytest.raises(TooFewSelectedError, match="selects 1 "):
        await read_under_parents(
            serving(*ngs_snps()),
            {
                "organismSinglePick": _PF,
                "variation_sample_meta": [{"field": "sex", "value": ["female"]}],
            },
            reads,
            about=_ABOUT,
        )

    [(param, context, _)] = reads.counts_read
    assert param == "variation_sample_meta"
    assert context["organismSinglePick"] == '["Plasmodium falciparum 3D7"]'
