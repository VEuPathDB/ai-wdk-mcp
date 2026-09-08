"""Which WDK searches carry an EDA subset, and what each one needs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError
from pydantic import model_validator
from veupathdb.domain.parameters.wdk_vocab import WDKVocabTerm, WDKVocabulary
from veupathdb.eda.models import EdaNewAnalysis
from veupathdb.errors import ValidationError
from veupathdb.json_types import JSONArray
from veupathdb.model import CamelModel
from veupathdb.wdk.wdk_models import WDKSearch

from veupathdb_mcp.catalog.searches import get_raw_searches

EDA_ANALYSIS_SPEC_PARAM = "eda_analysis_spec"
EDA_DATASET_ID_PARAM = "eda_dataset_id"

SUBSET_QUERY = "GenesByEdaSubset"
COMPUTE_QUERY = "GenesByEdaVizWithCompute"
WGCNA_QUERY = "GenesByWGCNAModule"

EDA_NOTEBOOK_TYPE_PROPERTY = "edaNotebookType"

# The one query that declares the spec parameter and never reads it.
_SPEC_IS_INERT = frozenset({WGCNA_QUERY})

_COMPUTE_QUERIES = frozenset({COMPUTE_QUERY})


@dataclass(frozen=True, slots=True)
class EdaBackedSearch:
    """One EDA-backed search, and what a caller must supply to run it."""

    search_name: str
    display_name: str
    query_name: str
    notebook_type: str | None
    reads_the_spec: bool
    needs_dataset_id: bool
    is_compute_backed: bool
    default_dataset_id: str | None


def is_eda_backed(search: WDKSearch) -> bool:
    """True when the search declares the analysis-spec parameter.

    Most EDA-backed searches carry no EDA token in the name, so the parameter
    is the only reliable test.
    """
    return EDA_ANALYSIS_SPEC_PARAM in search.param_names


def _dataset_default(search: WDKSearch) -> str | None:
    """The dataset id the expanded definition starts with, if it carries one."""
    return next(
        (
            param.initial_display_value
            for param in search.parameters or []
            if param.name == EDA_DATASET_ID_PARAM
        ),
        None,
    )


def eda_backed_search(search: WDKSearch) -> EdaBackedSearch | None:
    """Describe an EDA-backed search, or None when it is not one."""
    if not is_eda_backed(search):
        return None
    notebook = search.properties.get(EDA_NOTEBOOK_TYPE_PROPERTY, [])
    return EdaBackedSearch(
        search_name=search.url_segment,
        display_name=search.display_name,
        query_name=search.query_name,
        notebook_type=notebook[0] if notebook else None,
        reads_the_spec=search.query_name not in _SPEC_IS_INERT,
        needs_dataset_id=EDA_DATASET_ID_PARAM in search.param_names,
        is_compute_backed=search.query_name in _COMPUTE_QUERIES,
        default_dataset_id=_dataset_default(search),
    )


async def list_eda_backed(
    site_id: str,
    record_type: str = "transcript",
) -> list[EdaBackedSearch]:
    """Every EDA-backed search on a record type, ordered by name."""
    searches = await get_raw_searches(site_id, record_type)
    described = [eda_backed_search(s) for s in searches]
    return sorted(
        (d for d in described if d is not None),
        key=lambda d: d.search_name,
    )


def eda_backed_guidance(search: EdaBackedSearch) -> str:
    """What to do instead of proposing values for the two EDA parameters.

    The spec is a JSON document, not a value a parameter sheet can propose, so
    the EDA tools author it and the step-creation tool serializes it once.
    """
    lines = [
        (
            f"{search.search_name} is EDA-backed: its {EDA_ANALYSIS_SPEC_PARAM} "
            f"parameter carries a whole EDA analysis document, so do not propose a "
            f"value for it."
        ),
        (
            "Instead: search_eda_studies, then describe_eda_study, then "
            "open_eda_analysis, then set_eda_filters, then preview_eda_subset."
        ),
    ]
    if search.is_compute_backed:
        lines.append(
            "This search exports the genes that pass a volcano plot's "
            "thresholds, so run_eda_compute must complete before create_eda_step."
        )
    if not search.reads_the_spec:
        lines.append(
            "This search declares the parameter and never reads it; its gene "
            "list comes from its own parameters."
        )
    lines.append("create_eda_step builds the step from the open analysis.")
    return " ".join(lines)


class EdaStepRequest(CamelModel):
    """The two WDK parameters that carry an EDA subset into a step."""

    eda_dataset_id: str
    eda_analysis_spec: str

    @model_validator(mode="after")
    def _spec_names_the_same_dataset(self) -> EdaStepRequest:
        if not self.eda_analysis_spec:
            return self
        spec = EdaNewAnalysis.model_validate_json(self.eda_analysis_spec)
        if spec.study_id == self.eda_dataset_id:
            return self
        msg = (
            f"The analysis spec names {spec.study_id!r} and the step names "
            f"{self.eda_dataset_id!r}. Both values are a dataset id, not a "
            f"study id."
        )
        raise ValueError(msg)

    def wdk_parameters(self) -> dict[str, str]:
        """The step's ``parameters`` map, ready for ``WDKSearchConfig``."""
        return {
            EDA_DATASET_ID_PARAM: self.eda_dataset_id,
            EDA_ANALYSIS_SPEC_PARAM: self.eda_analysis_spec,
        }


_EMPTY_COMPUTE_SPEC = (
    f"{EDA_ANALYSIS_SPEC_PARAM} is empty, and this search exports the genes a "
    f"computation ranks, so the empty spec selects nothing."
)


def _spec_refusals(search: EdaBackedSearch, parameters: Mapping[str, str]) -> list[str]:
    """Every reason these two values are not an EDA analysis on this dataset."""
    spec = parameters.get(EDA_ANALYSIS_SPEC_PARAM, "")
    if not spec.strip():
        return [_EMPTY_COMPUTE_SPEC] if search.is_compute_backed else []
    try:
        EdaStepRequest(
            eda_dataset_id=parameters.get(EDA_DATASET_ID_PARAM, ""),
            eda_analysis_spec=spec,
        )
    except PydanticValidationError as exc:
        return [error["msg"] for error in exc.errors()]
    return []


def check_eda_parameters(search: WDKSearch, parameters: Mapping[str, str]) -> None:
    """Refuse a proposed analysis spec before WDK builds a step from it.

    The detail is the guidance, so a tool retry carries the route to the EDA
    tools that write the document.
    """
    described = eda_backed_search(search)
    if described is None:
        return
    refusals = _spec_refusals(described, parameters)
    if not refusals:
        return
    messages: JSONArray = list(refusals)
    rows: JSONArray = [{"param": EDA_ANALYSIS_SPEC_PARAM, "messages": messages}]
    raise ValidationError(
        title="eda_analysis_spec is written by PathFinder, not proposed",
        detail=eda_backed_guidance(described),
        errors=rows,
    )


UPLOAD_SENTINEL_PREFIX = "Upload a"

# The raw-counts arm reads "Upload an", so the article takes an optional n.
_UPLOAD_SENTINEL = re.compile(
    rf"^{re.escape(UPLOAD_SENTINEL_PREFIX)}n?\b", re.IGNORECASE
)

UPLOAD_SENTINEL_NOTE = (
    "This account owns no installed dataset for this search, so there is no "
    "value to choose and the search cannot run. The one entry the site returns "
    "is an invitation to upload, and running the search with it fails. Ask the "
    "user to install a dataset in My Workspace."
)


def is_upload_sentinel_vocabulary(vocabulary: WDKVocabulary | None) -> bool:
    """True when a one-term vocabulary is an empty state, not a choice.

    Both user-dataset vocabulary queries end with a UNION ALL arm that fires
    only when the user owns no installed dataset.
    """
    match vocabulary:
        case [WDKVocabTerm() as single]:
            return bool(_UPLOAD_SENTINEL.match(single.display))
        case _:
            return False
