"""A search runs a compute when it runs the generic compute query or opens an
EDA notebook; a subset search does neither."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests._support.recordings import TEST_ROOT
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog import eda_backed_guidance, eda_backed_search

pytestmark = pytest.mark.skipif(
    needs_qa_recording(
        TEST_ROOT / "unit/catalog/fixtures/plasmodb_eda_backed_searches.json"
    ),
    reason=NEEDS_QA_RECORDING,
)

_LISTING = Path(__file__).parent / "fixtures" / "plasmodb_eda_backed_searches.json"


def _recorded() -> dict[str, WDKSearch]:
    body = json.loads(_LISTING.read_text())["body"]
    return {
        search.url_segment: search
        for search in (WDKSearch.model_validate(entry) for entry in body)
    }


def _kinds() -> dict[str, tuple[bool, bool]]:
    kinds: dict[str, tuple[bool, bool]] = {}
    for name, search in _recorded().items():
        described = eda_backed_search(search)
        assert described is not None
        kinds[name] = (described.reads_the_spec, described.is_compute_backed)
    return kinds


def test_each_recorded_eda_backed_search_takes_the_kind_its_query_runs() -> None:
    assert _kinds() == {
        "GenesByEdaSubset": (True, False),
        "GenesByPhenotypeUserDataset": (True, False),
        "GenesByDESeqUserDataset": (True, True),
        "GenesByEdaVizWithCompute": (True, True),
        "GenesByPhenotypeEdaSubset_PlasmoDB_pknoA1H1_piggyBac_mutagenesis_MIS_MFS_Phenotype_RSRC": (
            True,
            False,
        ),
        "GenesByAntibodyArrayEdaSubset_PlasmoDB_Crompton_Mali_AntibodyArray_RSRC": (
            True,
            True,
        ),
        "GenesByRNASeqpfal3D7_Lee_Gambian_ebi_rnaSeq_RSRCWGCNAModules": (False, False),
        "GenesByRNASeqpfal3D7_Tonkin_Hill_Malaria_ebi_rnaSeq_RSRCDESeq": (True, True),
    }


def test_the_deseq_user_dataset_search_asks_for_the_compute_first() -> None:
    described = eda_backed_search(_recorded()["GenesByDESeqUserDataset"])
    assert described is not None

    guidance = eda_backed_guidance(described)

    assert "run_eda_compute must complete before create_eda_step" in guidance
