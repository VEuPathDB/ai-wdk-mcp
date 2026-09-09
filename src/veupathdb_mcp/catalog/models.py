"""What a catalog read answers: record types, searches and parameter specs."""

from dataclasses import dataclass

from pydantic import Field
from veupathdb.domain.parameters.wdk_vocab import (
    WDKDatasetParser,
    WDKFilterOntologyTerm,
    WDKVocabulary,
)
from veupathdb.model import CamelModel


class ParamSpecResponse(CamelModel):
    """Normalized parameter spec (UI-friendly) with typed vocab/ontology/parsers."""

    name: str
    display_name: str | None = Field(default=None)
    type: str
    allow_empty_value: bool = Field(default=False)
    allow_multiple_values: bool | None = Field(default=None)
    multi_pick: bool | None = Field(default=None)
    min_selected_count: int | None = Field(default=None)
    max_selected_count: int | None = Field(default=None)
    count_only_leaves: bool = Field(default=False)
    initial_display_value: str | None = Field(default=None)
    vocabulary: WDKVocabulary | None = None
    min: float | None = None
    max: float | None = None
    is_number: bool = Field(default=False)
    increment: float | None = None
    display_type: str | None = Field(default=None)
    is_visible: bool = Field(default=True)
    group: str | None = None
    dependent_params: list[str] = Field(default_factory=list)
    help: str | None = None
    # Filter-only metadata (populated only when type == "filter").
    ontology: list[WDKFilterOntologyTerm] | None = Field(default=None)
    filter_data_type_display_name: str | None = Field(default=None)
    # Dataset-only metadata (populated only when type == "input-dataset").
    parsers: list[WDKDatasetParser] | None = Field(default=None)
    default_id_list: str | None = Field(default=None)
    record_class_name: str | None = Field(default=None)


@dataclass(frozen=True, slots=True)
class RecordTypeInfo:
    """Simplified record type summary for API responses.

    Contains only the fields needed by transport handlers — the full
    WDK record type (with searches, properties, etc.) stays in the
    integration layer as ``WDKRecordType``.
    """

    name: str
    display_name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class SearchMatch:
    """A search result from search_for_searches.

    Replaces the untyped ``dict[str, str]`` that was previously threaded
    through scoring, site-search bonus, and final results.
    """

    name: str
    display_name: str
    description: str
    record_type: str
    category: str = ""
    returns: str = ""
    relevance: float = 0.0

    def to_dict(self) -> dict[str, str | float]:
        """Serialize to the camelCase dict shape expected by AI tool callers."""
        result: dict[str, str | float] = {
            "name": self.name,
            "displayName": self.display_name,
            "description": self.description,
            "recordType": self.record_type,
        }
        if self.category:
            result["category"] = self.category
        if self.returns:
            result["returns"] = self.returns
        if self.relevance > 0.0:
            result["relevance"] = round(self.relevance, 2)
        return result


# Searches that answer on every site and rank against no query, so a discovery
# result carries them whatever it ranked.
UNIVERSAL_SEARCHES: tuple[SearchMatch, ...] = (
    SearchMatch(
        name="GenesByText",
        display_name="Gene Text Search",
        description="Search all text fields for genes matching a keyword or phrase.",
        record_type="transcript",
        category="general",
        returns="transcript",
    ),
)
