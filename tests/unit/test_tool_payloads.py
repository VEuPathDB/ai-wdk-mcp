"""The payload shapes the MCP server and the agent toolsets both render."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field
from veupathdb.domain.parameters import StringValue
from veupathdb.testing import NEEDS_QA_RECORDING
from veupathdb.wdk import WDKStrategySummary

from veupathdb_mcp import tool_payloads
from veupathdb_mcp.catalog import searches
from veupathdb_mcp.controls.control_types import (
    ControlTargetData,
    ControlTestResult,
    NegativeControls,
    PositiveControls,
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
CATALOGS = Path(__file__).resolve().parents[2] / "data" / "catalogs"


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
        positive=PositiveControls(
            recovered_ids=["PF3D7_1222600", "PF3D7_1031000"],
            missed_ids=["PF3D7_0000001"],
        ),
        negative=NegativeControls(admitted_ids=[], excluded_ids=["PF3D7_0000002"]),
    )


def test_a_control_outcome_carries_the_counts_the_control_test_measured() -> None:
    outcome = ControlOutcome.model_validate(_control_test_result())

    assert outcome.search_name == "GenesByMolecularWeight"
    assert outcome.step_id == 77
    assert outcome.estimated_size == 132
    assert outcome.positive_intersection == 2
    assert outcome.positive_controls_count == 3
    assert outcome.positive_recall == pytest.approx(2 / 3)
    assert outcome.positive_recovered_ids == ["PF3D7_1222600", "PF3D7_1031000"]
    assert outcome.positive_missed_ids == ["PF3D7_0000001"]
    assert outcome.negative_intersection == 0
    assert outcome.negative_controls_count == 1
    assert outcome.negative_false_positive_rate == 0.0
    assert outcome.negative_admitted_ids == []
    assert outcome.negative_excluded_ids == ["PF3D7_0000002"]
    assert outcome.parameters == {
        "organism": StringValue(value="Plasmodium falciparum 3D7")
    }


def test_a_control_outcome_built_field_by_field_keeps_those_fields() -> None:
    outcome = ControlOutcome(
        step_id=123,
        estimated_size=100,
        positive_recovered_ids=["PF3D7_1222600", "PF3D7_1031000"],
        positive_missed_ids=[],
    )

    assert outcome.step_id == 123
    assert outcome.search_name == ""
    assert outcome.positive_intersection == 2
    assert outcome.positive_recall == 1.0
    assert outcome.negative_intersection is None


def test_a_control_outcome_with_one_list_of_a_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="both of its lists or neither"):
        ControlOutcome(negative_admitted_ids=["PF3D7_1222600"])


def test_a_control_test_without_control_sets_reports_no_counts() -> None:
    outcome = ControlOutcome.model_validate(
        ControlTestResult(site_id=SITE, record_type="transcript")
    )

    assert outcome.positive_intersection is None
    assert outcome.positive_recovered_ids is None
    assert outcome.negative_intersection is None
    assert outcome.negative_excluded_ids is None
    assert outcome.estimated_size == 0


def test_gene_sample_attributes_are_requested_for_gene_record_types() -> None:
    assert gene_sample_attributes("transcript") == [
        "gene_product",
        "gene_name",
        "organism",
    ]
    assert gene_sample_attributes("gene") == ["product", "name", "organism"]


class _RecordedAttribute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str


class _RecordedRecordType(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url_segment: str = Field(alias="urlSegment")
    attributes: list[_RecordedAttribute]


class _RecordedCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_types: list[_RecordedRecordType]


@pytest.mark.skip(reason=NEEDS_QA_RECORDING)
@pytest.mark.parametrize(
    "catalog", sorted(CATALOGS.glob("*.json")), ids=lambda path: path.stem
)
def test_each_gene_record_type_declares_the_attributes_its_sample_reads(
    catalog: Path,
) -> None:
    """A record type answers 400 to an attribute it does not declare."""
    recorded = _RecordedCatalog.model_validate_json(catalog.read_text())
    declared = {
        record_type.url_segment: {
            attribute.name for attribute in record_type.attributes
        }
        for record_type in recorded.record_types
    }
    sampled = [name for name in ("gene", "transcript") if name in declared]
    missing = {
        name: sorted(set(gene_sample_attributes(name) or []) - declared[name])
        for name in sampled
    }

    assert missing == {name: [] for name in sampled}


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
        step_id=42, format="tab", download_url="https://qa.plasmodb.org/x.tab"
    )

    assert payload.model_dump(by_alias=True) == {
        "stepId": 42,
        "format": "tab",
        "downloadUrl": "https://qa.plasmodb.org/x.tab",
    }


async def test_example_plans_fall_back_to_lexical_ranking_without_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = WDKStrategySummary(
        strategy_id=1,
        root_step_id=1,
        name="gametocyte genes",
        description="gametocyte surface antigens",
        is_public=True,
    )

    class _Api:
        async def list_public_strategies(self) -> list[WDKStrategySummary]:
            return [summary]

    async def unavailable(*args: object, **kwargs: object) -> list[dict[str, object]]:
        del args, kwargs
        raise EmbeddingUnavailableError(batch_size=1, cause="down")

    monkeypatch.setattr(tool_payloads, "get_strategy_api", lambda site_id: _Api())
    monkeypatch.setattr(tool_payloads, "rank_public_strategies_semantic", unavailable)

    plans = await tool_payloads.rank_example_plans(SITE, "gametocyte", limit=3)

    assert [plan["name"] for plan in plans] == ["gametocyte genes"]


def test_gene_sample_attributes_takes_the_record_type_the_caller_names() -> None:
    """No record type stands in for another: the signature admits no absence."""
    signature = inspect.signature(gene_sample_attributes, eval_str=True)

    assert signature.parameters["record_type"].annotation is str
