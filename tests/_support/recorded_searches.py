"""Recorded WDK search definitions, and the few named edits a test needs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import EDA_ANALYSIS_SPEC_PARAM

_SITE_RECORDINGS = Path(__file__).parent.parent / "unit" / "separation" / "fixtures"


def recorded_search(name: str) -> WDKSearchResponse:
    """One recorded search definition, as WDK sent it."""
    return WDKSearchResponse.model_validate(load_recorded(name).json_body())


def site_recorded_search(name: str) -> WDKSearchResponse:
    """A definition this suite recorded from plasmodb, trimmed as its provenance says."""
    recording = json.loads((_SITE_RECORDINGS / f"{name}.json").read_text())
    return WDKSearchResponse.model_validate(recording["body"])


def _molecular_weight_body() -> dict:
    return copy.deepcopy(load_recorded("search_genes_by_molecular_weight").json_body())


def gene_list_search() -> WDKSearchResponse:
    """GeneByLocusTag from the molecular-weight body: renamed, one input-dataset param.

    Two edits: the url segment, and the last parameter's name and type.
    """
    body = _molecular_weight_body()
    data = body["searchData"]
    data["urlSegment"] = "GeneByLocusTag"
    data["paramNames"][-1] = "ds_gene_ids"
    data["parameters"][-1] |= {"name": "ds_gene_ids", "type": "input-dataset"}
    return WDKSearchResponse.model_validate(body)


def analysis_backed_search() -> WDKSearchResponse:
    """The molecular-weight body with the analysis-spec parameter named in its list."""
    body = _molecular_weight_body()
    body["searchData"]["paramNames"].append(EDA_ANALYSIS_SPEC_PARAM)
    return WDKSearchResponse.model_validate(body)
