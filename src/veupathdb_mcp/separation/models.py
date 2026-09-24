"""The shapes a separation run takes, measures and returns."""

import math
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, JsonValue, model_validator
from veupathdb.domain.parameters import ParamValue
from veupathdb.domain.strategy import CombineOp
from veupathdb.model import CamelModel

from veupathdb_mcp.computed import computed
from veupathdb_mcp.controls import NegativeControls, PositiveControls
from veupathdb_mcp.separation.budget import CONFIRM_RESERVATION
from veupathdb_mcp.separation.stats import hypergeometric_log_sf

SeparationMode = Literal["exact", "similar"]

INFORMATIVE_P_VALUE = 0.05
"""The tail under which returned controls tell the positives from the negatives."""

Informs = Literal["recovering", "excluding", "neither"]
"""Which control set a candidate returns more of than chance, if either."""

_COMBINE_INPUTS = 2


def _beats_chance(held: int, tested: int, population: int, returned: int) -> bool:
    """Whether a draw of ``returned`` controls holds ``held`` of ``tested`` by chance
    with a probability under ``INFORMATIVE_P_VALUE``."""
    tail = hypergeometric_log_sf(held, population, tested, returned)
    return tail < math.log(INFORMATIVE_P_VALUE)


def informs(positive: PositiveControls, negative: NegativeControls) -> Informs:
    """Recovering when the returned controls are rich in positives, excluding when
    rich in negatives. Both tails draw every returned control from the tested ones."""
    population = positive.controls_count + negative.controls_count
    returned = positive.intersection_count + negative.intersection_count
    if _beats_chance(
        positive.intersection_count, positive.controls_count, population, returned
    ):
        return "recovering"
    if _beats_chance(
        negative.intersection_count, negative.controls_count, population, returned
    ):
        return "excluding"
    return "neither"


class CandidateSource(StrEnum):
    """Where a candidate criterion came from. The counts decide, whatever the source."""

    THREAD = "thread"
    LITERATURE = "literature"
    ENRICHMENT = "enrichment"
    ANNOTATION = "annotation"
    CATALOG = "catalog"


class CandidateProposal(CamelModel):
    """One literature hypothesis: catalog query words and the reference they came from."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=3, max_length=200)
    reference: str = Field(min_length=3, max_length=300)


class ThreadSearch(CamelModel):
    """A leaf the thread already runs, as its step states it."""

    model_config = ConfigDict(frozen=True)

    search_name: str
    parameters: dict[str, ParamValue]


class SeparationRequest(CamelModel):
    """The two control lists, the mode, the hypotheses and the request budget of a run."""

    model_config = ConfigDict(frozen=True)

    positives: list[str] = Field(min_length=1)
    negatives: list[str] = Field(min_length=1)
    mode: SeparationMode
    literature: list[CandidateProposal] = Field(default_factory=list)
    thread: list[ThreadSearch] = Field(default_factory=list)
    budget: int = Field(ge=CONFIRM_RESERVATION)

    @model_validator(mode="after")
    def _no_id_is_on_both_lists(self) -> Self:
        both = sorted(set(self.positives) & set(self.negatives))
        if both:
            msg = f"a control id is on both lists: {both}"
            raise ValueError(msg)
        return self


class Candidate(CamelModel):
    """One bound criterion, ready to run as a WDK step."""

    model_config = ConfigDict(frozen=True)

    id: str
    search_name: str
    display_name: str
    parameters: dict[str, ParamValue]
    source: CandidateSource
    basis: str
    reference: str | None = None


class MeasuredCandidate(CamelModel):
    """One candidate's real counts: its result size and where each control fell."""

    model_config = ConfigDict(frozen=True)

    candidate: Candidate
    result_size: int
    positive: PositiveControls
    negative: NegativeControls

    @computed
    def informs(self) -> Informs:
        """The control set its returned controls are rich in, if either."""
        return informs(self.positive, self.negative)


SkipReason = Literal[
    "not_a_gene_search",
    "transform",
    "needs_an_analysis",
    "takes_a_gene_list",
    "unbound_required",
    "vocabulary_miss",
    "wdk_refused",
    "budget",
    "duplicate",
    "source_skipped",
]


class SkippedCandidate(CamelModel):
    """A criterion the run did not measure, and why."""

    model_config = ConfigDict(frozen=True)

    search_name: str
    source: CandidateSource
    basis: str
    reason: SkipReason
    detail: str = ""


class SeparationNode(CamelModel):
    """The assembled boolean: a measured candidate, or a combine of two nodes."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["leaf", "combine"]
    candidate_id: str | None = None
    operator: Literal[CombineOp.INTERSECT, CombineOp.UNION, CombineOp.MINUS] | None = (
        None
    )
    inputs: list["SeparationNode"] = Field(default_factory=list)

    @model_validator(mode="after")
    def _the_shape_matches_the_kind(self) -> Self:
        if self.kind == "leaf":
            shaped = self.candidate_id is not None and not self.inputs
        else:
            shaped = self.candidate_id is None and len(self.inputs) == _COMBINE_INPUTS
        if not shaped or (self.kind == "leaf") != (self.operator is None):
            msg = "a leaf names one candidate; a combine, an operator and two inputs"
            raise ValueError(msg)
        return self


class SeparationResult(CamelModel):
    """What one run measured, what it assembled, and the assembled tree's own counts."""

    model_config = ConfigDict(frozen=True)

    site_id: str
    mode: SeparationMode
    organisms: list[str]
    positives: list[str]
    negatives: list[str]
    unresolved_positive: list[str]
    unresolved_negative: list[str]
    tree: SeparationNode | None
    positive: PositiveControls | None
    negative: NegativeControls | None
    result_size: int | None
    predicted_matches_read: bool
    shortfall: list[str]
    measured: list[MeasuredCandidate]
    skipped: list[SkippedCandidate]
    charged_requests: int
    budget: int

    @computed
    def separates(self) -> bool:
        """Every positive, and then no negative (exact) or a read that beats chance."""
        if self.positive is None or self.negative is None or self.positive.missed_ids:
            return False
        if self.mode == "exact":
            return not self.negative.admitted_ids
        return informs(self.positive, self.negative) == "recovering"


SeparationPhase = Literal[
    "resolved", "uploaded", "collected", "measured", "assembled", "confirmed"
]


class SeparationUpdate(CamelModel):
    """One progress row: a phase, its sentence, and the counts behind it.

    A measured row names the candidate it reports on.
    """

    model_config = ConfigDict(frozen=True)

    phase: SeparationPhase
    message: str
    candidate_id: str | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)


SeparationProgress = Callable[[SeparationUpdate], Awaitable[None]]
"""Where a run reports each row as it happens."""
