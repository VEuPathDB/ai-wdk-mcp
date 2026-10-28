"""A discovery result offers the site's text search and every radio-pair search."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests._support.orthomcl_catalog import orthomcl_record_types
from tests._support.recorded_searches import site_recorded_search
from tests._support.recordings import TEST_ROOT
from veupathdb.wdk import WDKSearch, WDKSearchResponse

from veupathdb_mcp.catalog import universal, universal_searches

type Listings = dict[str, list[WDKSearch]]

_CATALOG = TEST_ROOT / "unit" / "catalog" / "fixtures"


def _body(path: Path, key: str) -> WDKSearch:
    raw = json.loads(path.read_text())[key]
    return WDKSearchResponse.model_validate(raw).search_data


def _text() -> WDKSearch:
    return _body(
        TEST_ROOT / "unit/audit/fixtures/gene_ids_pfalNF54_piga.json", "search"
    )


def _interpro() -> WDKSearch:
    return _body(
        _CATALOG / "plasmodb_3d7_interpro_vocabulary_half_off.json", "response_json"
    )


def _unpaired() -> list[WDKSearch]:
    body = json.loads((_CATALOG / "plasmodb_transcript_searches.json").read_text())
    return [WDKSearch.model_validate(entry) for entry in body["body"]]


def _paired() -> list[WDKSearch]:
    return [
        site_recorded_search("search_go_term").search_data,
        _interpro(),
        site_recorded_search("search_metabolic_pathway").search_data,
    ]


class _HeldCatalog:
    def __init__(self, listings: Listings) -> None:
        self._listings = listings

    async def get_searches(self, _site_id: str, record_type: str) -> list[WDKSearch]:
        return self._listings.get(record_type, [])

    async def get_record_types(self, _site_id: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(url_segment=name) for name in self._listings]


def _hold(monkeypatch: pytest.MonkeyPatch, listings: Listings) -> None:
    held = _HeldCatalog(listings)
    monkeypatch.setattr(universal, "get_discovery_service", lambda: held)


async def test_plasmodb_offers_text_then_its_paired_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hold(monkeypatch, {"transcript": [*_unpaired(), *_paired(), _text()]})

    offered = await universal_searches("plasmodb", "transcript")

    assert [m.name for m in offered] == [
        "GenesByText",
        "GenesByGoTerm",
        "GenesByInterproDomain",
        "GenesByMetabolicPathway",
    ]
    assert {m.record_type for m in offered} == {"transcript"}


async def test_a_gene_question_reads_the_transcript_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hold(monkeypatch, {"transcript": [*_paired(), _text()]})

    offered = await universal_searches("plasmodb", "gene")

    assert [m.name for m in offered][:2] == ["GenesByText", "GenesByGoTerm"]


async def test_a_site_that_declares_no_pair_offers_text_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hold(monkeypatch, {"transcript": [*_unpaired(), _text()]})

    offered = await universal_searches("plasmodb", "transcript")

    assert [m.name for m in offered] == ["GenesByText"]


async def test_orthomcl_offers_its_paired_group_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listings = {rt.url_segment: rt.searches or [] for rt in orthomcl_record_types()}
    _hold(monkeypatch, listings)

    offered = await universal_searches("orthomcl", None)

    assert [(m.name, m.record_type) for m in offered] == [("GroupsByEcNumber", "group")]
