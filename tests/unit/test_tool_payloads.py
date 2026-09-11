"""The payload shapes the MCP server and the agent toolsets both render."""

from __future__ import annotations

import inspect

import pytest
from veupathdb.domain.parameters.values import StringValue
from veupathdb.wdk.wdk_models import WDKStrategySummary

from veupathdb_mcp import tool_payloads
from veupathdb_mcp.catalog import searches
from veupathdb_mcp.controls.control_types import (
    ControlSetData,
    ControlTargetData,
    ControlTestResult,
)
from veupathdb_mcp.embeddings.embedder import EmbeddingUnavailableError
from veupathdb_mcp.gene_lookup import MAX_GENE_IDS, normalize_gene_ids
from veupathdb_mcp.tool_payloads import (
    ControlOutcome,
    SearchCategory,
    SearchListing,
    StepDownloadUrl,
    TransformListing,
    gene_sample_attributes,
    list_search_categories,
    list_search_listings,
    list_transform_listings,
)

SITE = "plasmodb"


def _control_test_result() -> ControlTestResult:
    return ControlTestResult(
        site_id=SITE,
        record_type="transcript",
        target=ControlTargetData(
            search_name="GenesByMolecularWeight",
            parameters={"organism": StringValue(value="Plasmodium falciparum 3D7")},
            step_id=77,
            estimated_size=132,
        ),
        positive=ControlSetData(
            controls_count=3,
            intersection_count=2,
            intersection_ids_sample=["PF3D7_1222600", "PF3D7_1031000"],
            missing_ids_sample=["PF3D7_0000001"],
            target_estimated_size=132,
            recall=2 / 3,
        ),
        negative=ControlSetData(
            controls_count=1,
            intersection_count=0,
            unexpected_hits_sample=[],
            target_estimated_size=132,
            false_positive_rate=0.0,
        ),
    )


def test_a_control_outcome_carries_the_counts_the_control_test_measured() -> None:
    outcome = ControlOutcome.model_validate(_control_test_result())

    assert outcome.search_name == "GenesByMolecularWeight"
    assert outcome.step_id == 77
    assert outcome.estimated_size == 132
    assert outcome.positive_intersection == 2
    assert outcome.positive_controls_count == 3
    assert outcome.positive_recall == pytest.approx(2 / 3)
    assert outcome.positive_intersection_ids == ["PF3D7_1222600", "PF3D7_1031000"]
    assert outcome.positive_missing_ids == ["PF3D7_0000001"]
    assert outcome.negative_intersection == 0
    assert outcome.negative_controls_count == 1
    assert outcome.negative_false_positive_rate == 0.0
    assert outcome.parameters == {
        "organism": StringValue(value="Plasmodium falciparum 3D7")
    }


def test_a_control_outcome_built_field_by_field_keeps_those_fields() -> None:
    outcome = ControlOutcome(
        step_id=123,
        estimated_size=100,
        positive_intersection=2,
        positive_controls_count=2,
        positive_recall=1.0,
    )

    assert outcome.step_id == 123
    assert outcome.search_name == ""
    assert outcome.positive_intersection == 2
    assert outcome.negative_intersection is None


def test_a_control_test_without_control_sets_reports_no_counts() -> None:
    outcome = ControlOutcome.model_validate(
        ControlTestResult(site_id=SITE, record_type="transcript")
    )

    assert outcome.positive_intersection is None
    assert outcome.negative_intersection is None
    assert outcome.estimated_size == 0


def test_gene_sample_attributes_are_requested_for_gene_record_types() -> None:
    assert gene_sample_attributes("transcript") == [
        "gene_product",
        "gene_name",
        "organism",
    ]
    assert gene_sample_attributes("gene") == gene_sample_attributes("transcript")


def test_gene_sample_attributes_are_absent_for_a_non_gene_record_type() -> None:
    requested = {
        record_type: gene_sample_attributes(record_type)
        for record_type in ("popsetSequence", "organism", "dataset")
    }

    assert requested == {"popsetSequence": None, "organism": None, "dataset": None}


def test_normalize_gene_ids_trims_drops_blanks_and_de_duplicates() -> None:
    assert normalize_gene_ids([" PF3D7_1222600 ", "", "PF3D7_1222600", "  "]) == [
        "PF3D7_1222600"
    ]
    assert MAX_GENE_IDS == 200


async def test_search_listings_carry_the_names_the_catalog_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rows(site_id: str, record_type: str) -> list[dict[str, str]]:
        assert (site_id, record_type) == (SITE, "transcript")
        return [{"name": "GenesByMolecularWeight", "displayName": "Molecular Weight"}]

    monkeypatch.setattr(searches, "list_searches", rows)

    listings = await list_search_listings(SITE, "transcript")

    assert listings == [
        SearchListing(name="GenesByMolecularWeight", display_name="Molecular Weight")
    ]
    assert listings[0].model_dump(by_alias=True) == {
        "name": "GenesByMolecularWeight",
        "displayName": "Molecular Weight",
    }


async def test_transform_listings_carry_the_description_the_catalog_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rows(site_id: str, record_type: str) -> list[dict[str, str]]:
        del site_id, record_type
        return [
            {
                "name": "GenesByOrthologs",
                "displayName": "Orthologs",
                "description": "Transform to orthologs",
            }
        ]

    monkeypatch.setattr(searches, "list_transforms", rows)

    listings = await list_transform_listings(SITE, "transcript")

    assert listings == [
        TransformListing(
            name="GenesByOrthologs",
            display_name="Orthologs",
            description="Transform to orthologs",
        )
    ]


async def test_search_categories_carry_the_counts_the_ontology_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rows(
        site_id: str, record_type: str
    ) -> list[dict[str, str | int | list[str]]]:
        del site_id, record_type
        return [{"category": "Expression", "count": 2, "examples": ["a", "b"]}]

    monkeypatch.setattr(searches, "browse_search_categories", rows)

    categories = await list_search_categories(SITE, "transcript")

    assert categories == [
        SearchCategory(category="Expression", count=2, examples=["a", "b"])
    ]


def test_a_step_download_url_names_the_step_the_format_and_the_url() -> None:
    payload = StepDownloadUrl(
        step_id=42, format="tab", download_url="https://plasmodb.org/x.tab"
    )

    assert payload.model_dump(by_alias=True) == {
        "stepId": 42,
        "format": "tab",
        "downloadUrl": "https://plasmodb.org/x.tab",
    }


async def test_example_plans_fall_back_to_lexical_ranking_without_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = WDKStrategySummary(
        strategyId=1,
        rootStepId=1,
        name="gametocyte genes",
        description="gametocyte surface antigens",
        isPublic=True,
    )

    class _Api:
        async def list_public_strategies(self) -> list[WDKStrategySummary]:
            return [summary]

    async def unavailable(*args: object, **kwargs: object) -> list[dict[str, object]]:
        del args, kwargs
        raise EmbeddingUnavailableError(batch_size=1, cause=RuntimeError("down"))

    monkeypatch.setattr(tool_payloads, "get_strategy_api", lambda site_id: _Api())
    monkeypatch.setattr(tool_payloads, "rank_public_strategies_semantic", unavailable)

    plans = await tool_payloads.rank_example_plans(SITE, "gametocyte", limit=3)

    assert [plan["name"] for plan in plans] == ["gametocyte genes"]


def test_gene_sample_attributes_takes_the_record_type_the_caller_names() -> None:
    """No record type stands in for another: the signature admits no absence."""
    signature = inspect.signature(gene_sample_attributes, eval_str=True)

    assert signature.parameters["record_type"].annotation is str
