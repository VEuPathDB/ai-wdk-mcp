"""What a site catalog costs to build, and how a search is addressed in it.

A cold build fetches the whole catalog and encodes the site's semantic index.
Concurrent builds sum, so a process that starts one per site exceeds any
ceiling. A search carries two names and only the url segment is a path segment.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import VEuPathDBClient, WDKRecordType, WDKSearch, WDKSearchResponse

from veupathdb_mcp.catalog import discovery
from veupathdb_mcp.catalog.catalog_metadata import (
    DatasetMetadata,
    OntologyCategories,
)
from veupathdb_mcp.catalog.discovery import (
    _EMPTY_CATALOG_BYTES,
    CatalogPolicy,
    SearchCatalog,
)
from veupathdb_mcp.catalog.disk_cache import (
    CatalogSnapshot,
    save_catalog_cache,
    try_load_catalog_cache,
)
from veupathdb_mcp.catalog.param_adapters import adapt_param_specs_from_search
from veupathdb_mcp.embeddings.semantic_index import SemanticSearchIndex

_MOLECULAR_WEIGHT_PATH = "/record-types/transcript/searches/GenesByMolecularWeight"


def _catalog(
    site_id: str,
    *,
    cache_dir: Path | None = None,
    policy: CatalogPolicy | None = None,
    spawn: discovery.TaskSpawner = asyncio.create_task,
) -> SearchCatalog:
    """A catalog with its host dependencies named."""
    return SearchCatalog(
        site_id,
        cache_dir=cache_dir or Path("/nonexistent"),
        policy=policy or CatalogPolicy(),
        spawn=spawn,
    )


class _StubClient:
    """A client whose record-type read blocks until the test releases it."""

    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self.gate = gate

    async def get_record_types(self, *, expanded: bool) -> list[WDKRecordType]:
        del expanded
        if self.gate is not None:
            await self.gate.wait()
        return []


class _PathRecorder:
    """Captures the request path instead of reaching WDK."""

    def __init__(self, body: Any) -> None:
        self.body = body
        self.paths: list[str] = []

    async def __call__(self, path: str, **_: object) -> Any:
        self.paths.append(path)
        return self.body


def _search(name: str) -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(load_recorded(name).json_body())


def _molecular_weight() -> WDKSearchResponse:
    return _search("search_genes_by_molecular_weight")


def _genes_by_location() -> WDKSearch:
    return _search("search_genes_by_location").search_data


@pytest.fixture
def offline_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cut the WDK reads and the disk write out of ``_fetch_from_api``."""

    async def _datasets(*_args: object) -> DatasetMetadata:
        return DatasetMetadata({}, {})

    async def _ontology(*_args: object) -> OntologyCategories:
        return OntologyCategories({}, set(), {})

    monkeypatch.setattr(discovery, "load_dataset_metadata", _datasets)
    monkeypatch.setattr(discovery, "load_ontology_categories", _ontology)
    monkeypatch.setattr(discovery, "save_catalog_cache", lambda *_a: None)


async def test_only_one_catalog_is_built_at_a_time(
    offline_fetch: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del offline_fetch
    inflight = 0
    peak = 0

    def counting_build(self: SearchCatalog) -> None:
        nonlocal inflight, peak
        del self
        inflight += 1
        peak = max(peak, inflight)
        inflight -= 1

    monkeypatch.setattr(SearchCatalog, "_collect_semantic_index", counting_build)

    await asyncio.gather(
        _catalog("a")._fetch_from_api(_StubClient()),
        _catalog("b")._fetch_from_api(_StubClient()),
        _catalog("c")._fetch_from_api(_StubClient()),
    )

    assert peak == 1


async def test_a_catalog_reports_the_bytes_it_holds(tmp_path: Path) -> None:
    catalog = _catalog("testdb", cache_dir=tmp_path)
    snapshot = CatalogSnapshot(
        record_types=[],
        searches={"transcript": [WDKSearch(url_segment="A", display_name="A")]},
        dataset_summaries={},
        dataset_contacts={},
        search_categories={},
        available_categories=[],
    )
    save_catalog_cache("testdb", snapshot, cache_dir=tmp_path)
    restored = try_load_catalog_cache("testdb", cache_dir=tmp_path)
    assert restored is not None

    catalog._restore_from_snapshot(restored)
    catalog._semantic_index = SemanticSearchIndex(site_id="testdb")

    assert restored.payload_bytes == (tmp_path / "testdb.json").stat().st_size
    # The vectors live in Postgres, so a catalog costs what its snapshot does.
    assert catalog.memory_bytes == _EMPTY_CATALOG_BYTES + restored.payload_bytes * 4


async def test_an_unloaded_catalog_reports_a_size() -> None:
    assert _catalog("testdb").memory_bytes > 0


def _stale_snapshot() -> CatalogSnapshot:
    return CatalogSnapshot(
        cached_at=0.0,
        record_types=[],
        searches={},
        dataset_summaries={},
        dataset_contacts={},
        search_categories={},
        available_categories=[],
    )


class _SpawnRecorder:
    """Records what a catalog scheduled instead of running it."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def __call__(
        self, coro: Coroutine[Any, Any, None], /, *, name: str | None = None
    ) -> object:
        coro.close()
        self.names.append(name or "")
        return None


@pytest.fixture
def stale_cache(monkeypatch: pytest.MonkeyPatch) -> _SpawnRecorder:
    """A stale snapshot on every load, and a record of what was spawned."""

    def _no_index(_self: SearchCatalog) -> None:
        return None

    monkeypatch.setattr(
        discovery, "try_load_catalog_cache", lambda *_a: _stale_snapshot()
    )
    monkeypatch.setattr(SearchCatalog, "_collect_semantic_index", _no_index)
    return _SpawnRecorder()


async def test_a_refreshing_process_refreshes_a_stale_snapshot(
    stale_cache: _SpawnRecorder,
) -> None:
    catalog = _catalog("testdb", policy=CatalogPolicy(refresh=True), spawn=stale_cache)

    await catalog.load(_StubClient())

    assert stale_cache.names == ["catalog-refresh-testdb"]


async def test_a_serving_process_keeps_the_stale_snapshot_and_builds_nothing(
    stale_cache: _SpawnRecorder,
) -> None:
    """A build inside a served call is what exceeds the 2g ceiling."""
    catalog = _catalog("testdb", policy=CatalogPolicy(refresh=False), spawn=stale_cache)

    await catalog.load(_StubClient())

    assert stale_cache.names == []


class TestWdkSearch002TheUrlSegmentIsTheAddress:
    def test_wdk_search_002_a_search_carries_two_different_names(self) -> None:
        search = _molecular_weight().search_data

        assert search.url_segment == "GenesByMolecularWeight"
        assert search.full_name == "GeneQuestions.GenesByMolecularWeight"

    async def test_wdk_search_002_the_request_path_carries_the_url_segment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = VEuPathDBClient("https://example.invalid/service")
        get = _PathRecorder(
            load_recorded("search_genes_by_molecular_weight").json_body()
        )
        monkeypatch.setattr(client, "get", get)

        await client.get_search_details("transcript", "GenesByMolecularWeight")

        assert get.paths == [_MOLECULAR_WEIGHT_PATH]

    async def test_wdk_search_002_the_full_name_never_reaches_the_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = VEuPathDBClient("https://example.invalid/service")
        search = _molecular_weight().search_data
        get = _PathRecorder(
            load_recorded("search_genes_by_molecular_weight").json_body()
        )
        monkeypatch.setattr(client, "get", get)

        await client.get_search_details("transcript", search.url_segment)

        assert get.paths == [_MOLECULAR_WEIGHT_PATH]
        assert search.full_name not in get.paths[0]

    def test_wdk_search_002_the_full_name_is_a_404(self) -> None:
        recorded = load_recorded("search_by_full_name")

        assert recorded.provenance.status == 404
        assert recorded.raw_text().startswith(
            "Resource 'search: GeneQuestions.GenesByMolecularWeight' does not exist."
        )

    def test_wdk_search_002_the_full_name_is_kept_as_data(self) -> None:
        # It is the name a step's searchName carries and error messages use.
        assert _molecular_weight().search_data.full_name != ""


class TestWdkSearch001ASearchBelongsToOneRecordClass:
    def test_wdk_search_001_the_wrong_record_type_is_a_404(self) -> None:
        recorded = load_recorded("search_under_the_wrong_record_type")

        assert recorded.provenance.status == 404
        assert recorded.raw_text().strip() == (
            'There is no search "GenesByMolecularWeight" associated with '
            'record type "OrganismRecordClass"'
        )

    def test_wdk_search_001_the_refusal_names_the_record_class_full_name(self) -> None:
        # The path segment is the url segment; the comparison is against the
        # record class full name.
        body = load_recorded("search_under_the_wrong_record_type").raw_text()

        assert "OrganismRecordClass" in body
        assert 'record type "organism"' not in body

    def test_wdk_search_001_a_search_declares_one_output_record_class(self) -> None:
        search = _molecular_weight().search_data

        assert search.output_record_class_name == "transcript"

    def test_wdk_search_001_the_catalog_binds_a_search_to_one_record_type(self) -> None:
        # A client that caches "search X exists" without the record type it
        # exists under has cached half a fact.
        catalog = _catalog("plasmodb")
        catalog._searches["transcript"] = [WDKSearch(urlSegment="GenesByExonCount")]
        catalog._searches["organism"] = [WDKSearch(urlSegment="OrganismsByTaxon")]

        assert catalog.find_record_type_for_search("GenesByExonCount") == "transcript"
        assert catalog.find_search("organism", "GenesByExonCount") is None
        assert catalog.find_search("transcript", "GenesByExonCount") is not None


class TestWdkSearch004ParamNamesIsTheParameterList:
    """``supplementWithBasicParamInfo`` writes ``groups`` and ``paramNames`` from
    one call, so they agree on membership by construction.
    """

    def test_wdk_search_004_the_common_case_is_one_synthetic_group(self) -> None:
        search = _genes_by_location()

        assert [g.name for g in search.groups] == ["empty"]
        assert search.groups[0].display_type == "empty"

    def test_wdk_search_004_the_group_holds_every_parameter(self) -> None:
        search = _genes_by_location()

        assert search.groups[0].parameters == search.param_names

    def test_wdk_search_004_the_specs_come_from_the_parameter_list(self) -> None:
        search = _genes_by_location()

        specs = adapt_param_specs_from_search(search)

        assert sorted(specs) == sorted(search.param_names)

    def test_wdk_search_004_a_group_describes_no_parameter_of_its_own(self) -> None:
        # Its state is a name and four presentation fields.
        group = _genes_by_location().groups[0]

        assert set(group.model_dump(by_alias=True)) == {
            "name",
            "displayName",
            "description",
            "isVisible",
            "displayType",
            "parameters",
        }


class TestWdkSearch003AvailabilityIsADeploymentFact:
    def test_wdk_search_003_a_catalog_belongs_to_one_site(self) -> None:
        plasmo, toxo = _catalog("plasmodb"), _catalog("toxodb")

        assert plasmo.site_id == "plasmodb"
        assert toxo.site_id == "toxodb"

    def test_wdk_search_003_two_sites_do_not_share_a_search_set(self) -> None:
        plasmo, toxo = _catalog("plasmodb"), _catalog("toxodb")
        only_here = WDKSearch(urlSegment="GenesBySpanLogic")
        plasmo._searches["transcript"] = [only_here]

        assert plasmo.find_record_type_for_search("GenesBySpanLogic") == "transcript"
        assert toxo.find_record_type_for_search("GenesBySpanLogic") is None
