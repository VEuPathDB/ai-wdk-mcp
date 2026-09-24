"""The result shapes the MCP server and the agent toolsets both render."""

from __future__ import annotations

from typing import Self

from pydantic import ConfigDict, Field, model_validator
from veupathdb import JSONObject, get_logger
from veupathdb.domain.parameters import ParamValue
from veupathdb.model import CamelModel
from veupathdb.wdk import get_strategy_api

from veupathdb_mcp.catalog import searches
from veupathdb_mcp.catalog.public_strategy_search import (
    rank_public_strategies,
    rank_public_strategies_semantic,
)
from veupathdb_mcp.computed import computed
from veupathdb_mcp.controls.control_types import (
    ControlTestResult,
    NegativeControls,
    PositiveControls,
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


def _positive_lists(controls: PositiveControls | None) -> dict[str, list[str]]:
    """The positive-control lists of a flat control outcome, or nothing."""
    if controls is None:
        return {}
    return {
        "positive_recovered_ids": controls.recovered_ids,
        "positive_missed_ids": controls.missed_ids,
    }


def _negative_lists(controls: NegativeControls | None) -> dict[str, list[str]]:
    """The negative-control lists of a flat control outcome, or nothing."""
    if controls is None:
        return {}
    return {
        "negative_admitted_ids": controls.admitted_ids,
        "negative_excluded_ids": controls.excluded_ids,
    }


class ControlOutcome(CamelModel):
    """One control test, flat: what was tested and where each control was filed.

    A control kind the test was not given has None for both of its lists, and
    each count and rate is read from the two lists of its kind.
    """

    step_id: int | None = None
    search_name: str = ""
    parameters: dict[str, ParamValue] = Field(default_factory=dict)
    estimated_size: int = 0
    positive_recovered_ids: list[str] | None = None
    positive_missed_ids: list[str] | None = None
    negative_admitted_ids: list[str] | None = None
    negative_excluded_ids: list[str] | None = None
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
                    **_positive_lists(raw.positive),
                    **_negative_lists(raw.negative),
                }
            case _:
                return raw

    @model_validator(mode="after")
    def _each_kind_is_a_control_set(self) -> Self:
        self._positive()
        self._negative()
        return self

    def _positive(self) -> PositiveControls | None:
        match (self.positive_recovered_ids, self.positive_missed_ids):
            case (None, None):
                return None
            case (list() as recovered, list() as missed):
                return PositiveControls(recovered_ids=recovered, missed_ids=missed)
            case _:
                msg = "a positive control set names both of its lists or neither"
                raise ValueError(msg)

    def _negative(self) -> NegativeControls | None:
        match (self.negative_admitted_ids, self.negative_excluded_ids):
            case (None, None):
                return None
            case (list() as admitted, list() as excluded):
                return NegativeControls(admitted_ids=admitted, excluded_ids=excluded)
            case _:
                msg = "a negative control set names both of its lists or neither"
                raise ValueError(msg)

    @computed
    def positive_controls_count(self) -> int | None:
        """Every positive control the test was given."""
        positive = self._positive()
        return None if positive is None else positive.controls_count

    @computed
    def positive_intersection(self) -> int | None:
        """The positive controls the target returned."""
        positive = self._positive()
        return None if positive is None else positive.intersection_count

    @computed
    def positive_recall(self) -> float | None:
        """The share of the positive controls the target returned."""
        positive = self._positive()
        return None if positive is None else positive.recall

    @computed
    def negative_controls_count(self) -> int | None:
        """Every negative control the test was given."""
        negative = self._negative()
        return None if negative is None else negative.controls_count

    @computed
    def negative_intersection(self) -> int | None:
        """The negative controls the target returned."""
        negative = self._negative()
        return None if negative is None else negative.intersection_count

    @computed
    def negative_false_positive_rate(self) -> float | None:
        """The share of the negative controls the target returned."""
        negative = self._negative()
        return None if negative is None else negative.false_positive_rate


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
