"""The result shapes the MCP server and the agent toolsets both render."""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator
from veupathdb.domain.parameters.values import ParamValue
from veupathdb.json_types import JSONObject
from veupathdb.logging import get_logger
from veupathdb.model import CamelModel
from veupathdb.wdk.factory import get_strategy_api

from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.public_strategy_search import (
    rank_public_strategies,
    rank_public_strategies_semantic,
)
from veupathdb_mcp.controls.control_types import (
    ControlSetData,
    ControlTestResult,
)
from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError

__all__ = [
    "ControlOutcome",
    "DownloadLinks",
    "SearchCategory",
    "SearchListing",
    "StepDownloadUrl",
    "TransformListing",
    "gene_sample_attributes",
    "list_search_categories",
    "list_search_listings",
    "list_transform_listings",
    "rank_example_plans",
]

logger = get_logger(__name__)

_GENE_RECORD_TYPES = frozenset({"gene", "transcript"})
_GENE_SAMPLE_ATTRIBUTES = ("gene_product", "gene_name", "organism")


def gene_sample_attributes(record_type: str) -> list[str] | None:
    """The gene attributes a step read requests, or None to keep it id-only."""
    if record_type in _GENE_RECORD_TYPES:
        return list(_GENE_SAMPLE_ATTRIBUTES)
    return None


class SearchCategory(CamelModel):
    """One ontology category of a site's searches, with example search names."""

    model_config = ConfigDict(frozen=True)

    category: str
    count: int
    examples: list[str]


class SearchListing(CamelModel):
    """One search of a record type, by name."""

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str


class TransformListing(CamelModel):
    """One search that accepts an input step, and what it does."""

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    description: str


class StepDownloadUrl(CamelModel):
    """Where one step's results download from, and in what format."""

    model_config = ConfigDict(frozen=True)

    step_id: int
    format: str
    download_url: str


class DownloadLinks(CamelModel):
    """Where an exported result downloads from, and for how long."""

    json_url: str | None = None
    csv_url: str | None = None
    expires_in_seconds: int | None = None


def _positive_fields(data: ControlSetData | None) -> dict[str, object]:
    """The positive-control half of a flat control outcome, or nothing."""
    if data is None:
        return {}
    return {
        "positive_intersection": data.intersection_count,
        "positive_controls_count": data.controls_count,
        "positive_recall": data.recall,
        "positive_intersection_ids": data.intersection_ids_sample,
        "positive_missing_ids": data.missing_ids_sample,
    }


def _negative_fields(data: ControlSetData | None) -> dict[str, object]:
    """The negative-control half of a flat control outcome, or nothing."""
    if data is None:
        return {}
    return {
        "negative_intersection": data.intersection_count,
        "negative_controls_count": data.controls_count,
        "negative_false_positive_rate": data.false_positive_rate,
        "negative_intersection_ids": data.intersection_ids_sample,
    }


class ControlOutcome(CamelModel):
    """One control test, flat: what was tested and what the controls recovered."""

    step_id: int | None = None
    search_name: str = ""
    parameters: dict[str, ParamValue] = Field(default_factory=dict)
    estimated_size: int = 0
    positive_intersection: int | None = None
    positive_controls_count: int | None = None
    positive_recall: float | None = None
    positive_intersection_ids: list[str] = Field(default_factory=list)
    positive_missing_ids: list[str] = Field(default_factory=list)
    negative_intersection: int | None = None
    negative_controls_count: int | None = None
    negative_false_positive_rate: float | None = None
    negative_intersection_ids: list[str] = Field(default_factory=list)
    downloads: DownloadLinks | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten_control_test(cls, raw: object) -> object:
        """Flatten the target and the control sets of a control-test result."""
        match raw:
            case ControlTestResult():
                return {
                    "step_id": raw.target.step_id,
                    "search_name": raw.target.search_name,
                    "parameters": raw.target.parameters,
                    "estimated_size": raw.target.estimated_size or 0,
                    **_positive_fields(raw.positive),
                    **_negative_fields(raw.negative),
                }
            case _:
                return raw


async def list_search_categories(
    site_id: str,
    record_type: str,
) -> list[SearchCategory]:
    """The site ontology's search categories, with example search names."""
    rows = await searches.browse_search_categories(site_id, record_type)
    return [SearchCategory.model_validate(row) for row in rows]


async def list_search_listings(
    site_id: str,
    record_type: str,
) -> list[SearchListing]:
    """Every search name of one record type, without descriptions."""
    rows = await searches.list_searches(site_id, record_type)
    return [SearchListing.model_validate(row) for row in rows]


async def list_transform_listings(
    site_id: str,
    record_type: str,
) -> list[TransformListing]:
    """The searches that accept an input step, with their descriptions."""
    rows = await searches.list_transforms(site_id, record_type)
    return [TransformListing.model_validate(row) for row in rows]


async def rank_example_plans(
    site_id: str,
    query: str,
    limit: int = 3,
) -> list[JSONObject]:
    """Rank the site's public strategies against a goal.

    Lexical token overlap ranks them when the index cannot answer.
    """
    strategies = await get_strategy_api(site_id).list_public_strategies()
    try:
        return await rank_public_strategies_semantic(
            strategies, query, site_id=site_id, limit=limit
        )
    except SemanticIndexUnavailableError as exc:
        logger.warning("Semantic strategy ranking unavailable", error=str(exc))
        return rank_public_strategies(strategies, query=query, limit=limit)
