import pytest
from tests._support.control_run_wdk import RunFakeAPI, patch_control_account
from veupathdb.domain import SearchContext
from veupathdb.wdk import WDKRecordType, WDKSearch

from veupathdb_mcp.catalog import param_resolution, searches
from veupathdb_mcp.catalog.param_resolution import expand_search_details_with_params
from veupathdb_mcp.catalog.search_inspection import UnknownSearchError, inspect_search
from veupathdb_mcp.catalog.searches import (
    UnlistedSearchError,
    catalog_record_type,
    listed_record_type,
    resolve_search_record_type,
)
from veupathdb_mcp.controls import (
    CONTROLS_PARAM,
    CONTROLS_SEARCH,
    IntersectionConfig,
    control_tests,
    run_positive_negative_controls,
)

LISTED = {"transcript": ["GenesByMolecularWeight", "GenesByLocation"]}


class Catalog:
    def find_record_type_for_search(self, search_name: str) -> str | None:
        return next((rt for rt, names in LISTED.items() if search_name in names), None)

    def get_record_types(self) -> list[WDKRecordType]:
        return [WDKRecordType(url_segment=rt) for rt in LISTED]

    def get_searches(self, record_type: str) -> list[WDKSearch]:
        return [
            WDKSearch.model_validate({"urlSegment": name})
            for name in LISTED[record_type]
        ]


class Discovery:
    async def get_catalog(self, site_id: str) -> Catalog:
        return Catalog()


@pytest.fixture(autouse=True)
def catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(searches, "get_discovery_service", Discovery)


async def test_a_listed_search_reads_its_record_type() -> None:
    ctx = SearchContext("plasmodb", "gene", "GenesByLocation")

    assert await catalog_record_type(ctx) == "transcript"


async def test_an_unlisted_search_reads_no_record_type_whatever_was_asked() -> None:
    ctx = SearchContext("plasmodb", "transcript", "GenesByNothing")

    assert await catalog_record_type(ctx) is None


async def test_an_unlisted_search_is_refused_naming_it() -> None:
    with pytest.raises(
        UnlistedSearchError, match="plasmodb lists no search GenesByNothing"
    ):
        await resolve_search_record_type("plasmodb", "GenesByNothing", None)


async def test_an_unlisted_search_is_inspected_as_unknown_with_the_listed_names() -> (
    None
):
    with pytest.raises(UnknownSearchError) as refused:
        await inspect_search("plasmodb", "GenesByMolecularWeigh")

    assert "GenesByMolecularWeight" in refused.value.guidance


async def test_a_control_run_on_an_unlisted_search_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = patch_control_account(monkeypatch, RunFakeAPI())
    monkeypatch.setattr(control_tests, "listed_record_type", listed_record_type)
    config = IntersectionConfig(
        site_id="plasmodb",
        record_type="transcript",
        target_search_name="GenesByNothing",
        target_parameters={},
        controls_search_name=CONTROLS_SEARCH,
        controls_param_name=CONTROLS_PARAM,
    )

    with pytest.raises(UnlistedSearchError):
        await run_positive_negative_controls(config, positive_controls=["PF3D7_1"])

    assert account.datasets == []


async def test_the_details_of_an_unlisted_search_are_refused_before_a_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _discovery(ctx: SearchContext) -> tuple[None, set[str]]:
        return None, set()

    monkeypatch.setattr(
        param_resolution, "_load_discovery_details_and_allowed", _discovery
    )
    monkeypatch.setattr(param_resolution, "get_wdk_client", lambda site_id: None)

    with pytest.raises(UnlistedSearchError):
        await expand_search_details_with_params(
            SearchContext("plasmodb", "transcript", "GenesByNothing"), None
        )
