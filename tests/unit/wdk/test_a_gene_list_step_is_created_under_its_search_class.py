import pytest
from tests._support.enrichment_wdk import GO_ROW, FakeStrategyAPI, wdk
from tests._support.listed_searches import list_searches
from veupathdb.auth_context import veupathdb_auth_token_ctx

from veupathdb_mcp.catalog.searches import UnlistedSearchError
from veupathdb_mcp.wdk import IdListStepCountError, gene_set_steps
from veupathdb_mcp.wdk.enrichment.service import EnrichmentService
from veupathdb_mcp.wdk.gene_set_steps import frozen_step_id

__all__ = ["wdk"]

GENE = "PF3D7_0100100"


@pytest.fixture(autouse=True)
def account() -> object:
    gene_set_steps._FROZEN_STEPS.clear()
    reset = veupathdb_auth_token_ctx.set("registered-token")
    yield
    veupathdb_auth_token_ctx.reset(reset)


async def test_a_gene_set_step_is_created_under_the_class_its_search_is_listed_under(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_searches(monkeypatch, {"transcript": ["GeneByLocusTag"]})

    await frozen_step_id("plasmodb", [GENE])

    [(spec, record_type)] = wdk.steps
    assert (spec.search_name, record_type) == ("GeneByLocusTag", "transcript")


async def test_a_gene_set_step_on_a_site_with_no_gene_list_search_writes_nothing(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_searches(monkeypatch, {"group": ["GroupsByNameList"]})

    with pytest.raises(
        UnlistedSearchError, match="orthomcl lists no search GeneByLocusTag"
    ):
        await frozen_step_id("orthomcl", [GENE])

    assert wdk.calls == []


async def test_an_enrichment_target_is_created_under_its_search_class(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_searches(monkeypatch, {"transcript": ["GenesByMolecularWeight"]})
    wdk.rows["go-enrichment"] = [GO_ROW]

    await EnrichmentService().run_batch(
        site_id="plasmodb",
        analysis_types=["go_function"],
        search_name="GenesByMolecularWeight",
        parameters={},
    )

    [(spec, record_type)] = wdk.steps
    assert (spec.search_name, record_type) == ("GenesByMolecularWeight", "transcript")


async def test_an_enrichment_target_no_record_type_lists_is_refused_before_a_step(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_searches(monkeypatch, {"transcript": ["GenesByMolecularWeight"]})

    with pytest.raises(
        UnlistedSearchError, match="plasmodb lists no search GenesByNothing"
    ):
        await EnrichmentService().run_batch(
            site_id="plasmodb",
            analysis_types=["go_function"],
            search_name="GenesByNothing",
            parameters={},
        )

    assert wdk.calls == []


GROUPS = ["OG8_0000011", "OG8_0000003", "OGR8r1_0000039"]


async def test_group_ids_are_saved_as_a_group_name_list_step(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_searches(monkeypatch, {"group": ["GroupsByNameList"]})

    step_id = await frozen_step_id("orthomcl", GROUPS, record_type="group")

    [(spec, record_type)] = wdk.steps
    assert (step_id, spec.search_name, record_type) == (
        101,
        "GroupsByNameList",
        "group",
    )
    assert spec.search_config.parameters == {"group_names": "4242"}
    assert wdk.datasets == [GROUPS]
    assert wdk.calls[-1] == "get_step_count"


async def test_a_group_step_that_counts_other_than_its_ids_is_refused(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_searches(monkeypatch, {"group": ["GroupsByNameList"]})

    async def mapped(step_id: int, user_id: str | None = None) -> int:
        del step_id, user_id
        return len(GROUPS) + 1

    monkeypatch.setattr(wdk, "get_step_count", mapped)

    with pytest.raises(IdListStepCountError) as refused:
        await frozen_step_id("orthomcl", GROUPS, record_type="group")

    assert (refused.value.uploaded, refused.value.counted) == (3, 4)
    assert wdk.deleted == [202]
    assert gene_set_steps._FROZEN_STEPS == {}


async def test_a_gene_step_reads_no_count(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_searches(monkeypatch, {"transcript": ["GeneByLocusTag"]})

    await frozen_step_id("plasmodb", [GENE])

    assert "get_step_count" not in wdk.calls


async def test_group_ids_that_differ_only_in_case_are_uploaded_once(
    wdk: FakeStrategyAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    list_searches(monkeypatch, {"group": ["GroupsByNameList"]})
    spelled = ["OG8_0000011", "og8_0000011", "OGR8r1_0000039", "ogr8R1_0000039"]

    step_id = await frozen_step_id("orthomcl", spelled, record_type="group")

    assert step_id == 101
    assert wdk.datasets == [["OG8_0000011", "OGR8r1_0000039"]]
    assert wdk.deleted == []
