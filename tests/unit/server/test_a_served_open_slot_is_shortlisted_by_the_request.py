"""The served binding shows an open slot's vocabulary whole up to the sheet
limit, and the request's shortlist of a longer one."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters import UnboundParameter
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import ParameterInfo, ParamFetcher, shortlist_slot
from veupathdb_mcp.catalog.param_formatting import format_param_info_typed
from veupathdb_mcp.catalog.shortlist import DIRECT_MAX, TOP_K
from veupathdb_mcp.tools import catalog_tools

_PF3D7 = "Plasmodium falciparum 3D7"


def _sheet(name: str) -> list[ParameterInfo]:
    body = load_recorded(name).json_body()
    return format_param_info_typed(
        WDKSearchResponse.model_validate(body).search_data.parameters or []
    )


def _portal_sheet() -> list[ParameterInfo]:
    """The PlasmoDB sheet with VectorBase's organisms listed before its own."""
    vectorbase = next(
        info
        for info in _sheet("search_genes_by_gene_model_chars")
        if info.name == "organism_select_none"
    )
    return [
        info.model_copy(
            update={"vocab_leaves": [*vectorbase.vocabulary(), *info.vocabulary()]}
        )
        if info.name == "organism"
        else info
        for info in _sheet("search_genes_by_exon_count")
    ]


def _serve(monkeypatch: pytest.MonkeyPatch, infos: list[ParameterInfo]) -> None:
    def fetch(site_id: str, record_type: str, search_name: str) -> ParamFetcher:
        del site_id, record_type, search_name

        async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
            del context
            return infos

        return fetch_at

    monkeypatch.setattr(catalog_tools, "wdk_fetch_at", fetch)


async def _organism_slot(criterion: str) -> UnboundParameter:
    resolved = await catalog_tools.resolve_search_parameters(
        "plasmodb", "GenesByExonCount", criterion=criterion
    )
    return next(s for s in resolved.open_slots if s.param_name == "organism")


async def test_a_sheet_sized_vocabulary_is_served_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, _sheet("search_genes_by_exon_count"))

    slot = await _organism_slot("falciparum 3D7 genes with many exons")

    assert len(slot.options) == 90
    assert slot.options.index(_PF3D7) == 25


async def test_a_longer_vocabulary_is_served_as_the_requests_shortlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    infos = _portal_sheet()
    whole = next(i for i in infos if i.name == "organism").vocabulary()
    assert len(whole) == 279 > DIRECT_MAX
    assert [o.value for o in whole].index(_PF3D7) == 214 >= TOP_K
    _serve(monkeypatch, infos)

    slot = await _organism_slot("falciparum 3D7 genes with many exons")

    assert len(slot.options) == TOP_K
    assert slot.options[0] == _PF3D7
    assert "279 values" in slot.question
    assert "query=" in slot.question


async def test_a_contrast_slot_is_served_as_the_requests_shortlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SNP sheet with its sample filter as a reference and comparison pair."""
    _serve(
        monkeypatch,
        [
            pair
            for info in _sheet("search_genes_by_ngs_snps")
            for pair in (
                [
                    info.model_copy(update={"name": f"{side}_samples"})
                    for side in ("ref", "comp")
                ]
                if info.name == "variation_sample_meta"
                else [info]
            )
        ],
    )

    resolved = await catalog_tools.resolve_search_parameters(
        "plasmodb", "GenesByNgsSnps", criterion="Gambia isolates against Kenya"
    )

    [reference, comparison] = [
        s for s in resolved.open_slots if s.param_name.endswith("_samples")
    ]
    assert len(reference.options) == TOP_K
    assert {"VAR_8e68b3e5=Gambia", "VAR_8e68b3e5=Kenya"} <= set(reference.options[:2])
    assert "1521 values" in comparison.question


def test_a_slot_within_the_sheet_limit_is_kept_as_it_is() -> None:
    slot = UnboundParameter(param_name="organism", options=["b", "a"])

    assert shortlist_slot(slot, "a") == slot
