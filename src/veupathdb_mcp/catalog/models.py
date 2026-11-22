"""What a catalog read answers: record types, searches and parameter specs."""

from dataclasses import dataclass

from pydantic import Field, JsonValue
from veupathdb.domain.parameters import (
    WDKDatasetParser,
    WDKFilterOntologyTerm,
    WDKVocabulary,
)
from veupathdb.model import CamelModel


class _ParamSpecFields(CamelModel):
    name: str
    display_name: str | None = Field(default=None)
    type: str
    allow_empty_value: bool = Field(default=False)
    allow_multiple_values: bool | None = Field(default=None)
    multi_pick: bool | None = Field(default=None)
    min_selected_count: int | None = Field(default=None)
    max_selected_count: int | None = Field(default=None)
    count_only_leaves: bool = Field(default=False)
    vocabulary: WDKVocabulary | None = None
    min: float | None = None
    max: float | None = None
    is_number: bool = Field(default=False)
    increment: float | None = None
    display_type: str | None = Field(default=None)
    is_visible: bool = Field(default=True)
    is_read_only: bool = False
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


class ParamSpecResponse(_ParamSpecFields):
    """Normalized parameter spec (UI-friendly) with the default as WDK holds it."""

    initial_display_value: str | None = Field(default=None)


class StatedParamSpec(_ParamSpecFields):
    """A parameter spec a model reads, with the default in the form it is stated."""

    # None when WDK holds no default a caller can state.
    default: JsonValue = None


@dataclass(frozen=True, slots=True)
class RecordTypeInfo:
    """Simplified record type summary for API responses.

    Contains only the fields needed by transport handlers; the full
    WDK record type (with searches, properties, etc.) stays in the
    integration layer as ``WDKRecordType``.
    """

    name: str
    display_name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class SearchMatch:
    """One search that search_for_searches ranked against a query."""

    name: str
    display_name: str
    description: str
    record_type: str
    category: str = ""
    returns: str = ""
    # The score divided by the best score of the same answer, so the top hit
    # reads 1.0 whether or not it matches the query well.
    relevance: float = 0.0
    # The cosine of the query against the search's indexed text. None when
    # the semantic index did not score this search.
    semantic_similarity: float | None = None
    # The probability a Decisions choice over the offered searches gave this
    # search. None when the choice did not pick it.
    decision_probability: float | None = None

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
        if self.semantic_similarity is not None:
            result["semanticSimilarity"] = round(self.semantic_similarity, 2)
        if self.decision_probability is not None:
            result["decisionProbability"] = round(self.decision_probability, 2)
        return result
