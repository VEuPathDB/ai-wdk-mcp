"""An EDA-backed search is identified by its parameters, never by its name."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters.wdk_vocab import (
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
)
from veupathdb.wdk.wdk_models import WDKSearch
from veupathdb.wdk.wdk_parameters import (
    WDKParameter,
    WDKStringParam,
)

from veupathdb_mcp.catalog import eda_backed, search_inspection
from veupathdb_mcp.catalog.eda_backed import (
    eda_backed_guidance,
    eda_backed_search,
    is_eda_backed,
    is_upload_sentinel_vocabulary,
    list_eda_backed,
)
from veupathdb_mcp.catalog.search_inspection import inspect_search

from .conftest import vocab_terms


def _search(
    *,
    name: str,
    params: list[str],
    query: str = "",
    notebook: str | None = None,
    parameters: list[WDKParameter] | None = None,
) -> WDKSearch:
    properties: dict[str, list[str]] = {}
    if notebook is not None:
        properties["edaNotebookType"] = [notebook]
    return WDKSearch(
        url_segment=name,
        display_name=name,
        param_names=params,
        query_name=query,
        properties=properties,
        parameters=parameters,
    )


def test_a_search_with_the_spec_parameter_is_eda_backed_without_eda_in_its_name() -> (
    None
):
    """52 of the 68 are named GenesByRNASeq<dataset>DESeq."""
    search = _search(
        name="GenesByRNASeqpfal3D7_Febrile_temps_RNASeq_ebi_rnaSeq_RSRCDESeq",
        params=["eda_dataset_id", "eda_analysis_spec"],
        query="GenesByEdaVizWithCompute",
        notebook="differentialExpressionNotebook",
    )
    assert is_eda_backed(search) is True


def test_a_search_with_eda_in_its_name_and_no_spec_parameter_is_not_eda_backed() -> (
    None
):
    search = _search(name="GenesByEdaSomethingElse", params=["organism"])
    assert is_eda_backed(search) is False


def test_a_plain_search_is_not_eda_backed() -> None:
    search = _search(name="GenesByText", params=["text_search_organism"])
    assert is_eda_backed(search) is False


def test_the_generic_subset_search_needs_the_dataset_id_set() -> None:
    """GenesByEdaSubsetGeneric hides the parameter; the caller must supply it."""
    described = eda_backed_search(
        _search(
            name="GenesByPhenotypeEdaSubset_X",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
        )
    )
    assert described is not None
    assert described.needs_dataset_id is True
    assert described.is_compute_backed is False


def test_a_compute_backed_search_is_marked_as_such() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByRNASeqXDESeq",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaVizWithCompute",
            notebook="differentialExpressionNotebook",
        )
    )
    assert described is not None
    assert described.is_compute_backed is True
    assert described.notebook_type == "differentialExpressionNotebook"


def test_the_wgcna_search_declares_the_spec_and_never_reads_it() -> None:
    """Its query is a plain sqlQuery; setting the spec changes nothing."""
    described = eda_backed_search(
        _search(
            name="GenesByRNASeqXWGCNAModules",
            params=[
                "eda_dataset_id",
                "eda_analysis_spec",
                "wgcnaParam",
                "wgcna_correlation_cutoff",
            ],
            query="GenesByWGCNAModule",
            notebook="wgcnaCorrelationNotebook",
        )
    )
    assert described is not None
    assert described.reads_the_spec is False


def test_a_subset_search_reads_the_spec() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByPhenotypeEdaSubset_X",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
        )
    )
    assert described is not None
    assert described.reads_the_spec is True


def test_a_search_that_is_not_eda_backed_describes_as_none() -> None:
    assert eda_backed_search(_search(name="GenesByText", params=["x"])) is None


def test_a_name_filter_would_find_far_fewer_than_the_predicate() -> None:
    """13 of 68 live have Eda in the name. The predicate is the invariant."""
    searches = [
        _search(
            name=f"GenesByRNASeqDataset{i}DESeq",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaVizWithCompute",
        )
        for i in range(52)
    ] + [
        _search(
            name="GenesByPhenotypeEdaSubset_X",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
        )
    ]
    by_predicate = [s for s in searches if is_eda_backed(s)]
    by_name = [s for s in searches if "Eda" in s.url_segment]
    assert len(by_predicate) == 53
    assert len(by_name) == 1


def test_a_search_without_the_dataset_parameter_does_not_need_it() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByEdaSpecOnly",
            params=["eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
        )
    )
    assert described is not None
    assert described.needs_dataset_id is False


def test_the_dataset_default_comes_from_the_expanded_parameter() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByPhenotypeUserDataset",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
            parameters=[
                WDKStringParam(name="eda_analysis_spec", initial_display_value=None),
                WDKStringParam(
                    name="eda_dataset_id",
                    initial_display_value="DS_eeca6a5476",
                ),
            ],
        )
    )
    assert described is not None
    assert described.default_dataset_id == "DS_eeca6a5476"


def test_the_dataset_default_is_none_when_the_definition_is_not_expanded() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByPhenotypeUserDataset",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
        )
    )
    assert described is not None
    assert described.default_dataset_id is None


async def test_list_eda_backed_keeps_only_the_eda_searches_in_name_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = [
        _search(
            name="GenesByRNASeqZDESeq",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaVizWithCompute",
        ),
        _search(name="GenesByText", params=["text_search_organism"]),
        _search(
            name="GenesByPhenotypeEdaSubset_X",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
        ),
    ]

    async def _raw(site_id: str, record_type: str) -> list[WDKSearch]:
        assert site_id == "plasmodb"
        assert record_type == "transcript"
        return catalog

    monkeypatch.setattr(eda_backed, "get_raw_searches", _raw)

    described = await list_eda_backed("plasmodb")
    assert [d.search_name for d in described] == [
        "GenesByPhenotypeEdaSubset_X",
        "GenesByRNASeqZDESeq",
    ]


def test_an_eda_backed_search_names_the_two_parameters_it_needs() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByPhenotypeEdaSubset_X",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
        )
    )
    assert described is not None
    assert described.needs_dataset_id
    assert described.reads_the_spec


def test_the_guidance_tells_the_model_to_use_the_eda_tools() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByRNASeqXDESeq",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaVizWithCompute",
            notebook="differentialExpressionNotebook",
        )
    )
    assert described is not None
    guidance = eda_backed_guidance(described)
    assert "eda_analysis_spec" in guidance
    assert "create_eda_step" in guidance
    assert "run_eda_compute" in guidance
    assert "set_criterion" not in guidance


def test_the_subset_guidance_does_not_mention_a_compute() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByPhenotypeEdaSubset_X",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
        )
    )
    assert described is not None
    guidance = eda_backed_guidance(described)
    assert "run_eda_compute" not in guidance
    assert "open_eda_analysis" in guidance


def test_the_inert_search_guidance_says_the_spec_is_never_read() -> None:
    described = eda_backed_search(
        _search(
            name="GenesByRNASeqXWGCNAModules",
            params=["eda_dataset_id", "eda_analysis_spec", "wgcnaParam"],
            query="GenesByWGCNAModule",
        )
    )
    assert described is not None
    assert "never reads it" in eda_backed_guidance(described)


def _stub_definition(monkeypatch: pytest.MonkeyPatch, definition: WDKSearch) -> None:
    async def _record_type(_site: str, _search: str, _rt: str | None) -> str:
        return "transcript"

    async def _definition(_site: str, _rt: str, _search: str) -> WDKSearch:
        return definition

    monkeypatch.setattr(search_inspection, "resolve_search_record_type", _record_type)
    monkeypatch.setattr(search_inspection, "read_search_definition", _definition)


async def test_inspecting_an_eda_backed_search_carries_the_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_definition(
        monkeypatch,
        _search(
            name="GenesByRNASeqXDESeq",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaVizWithCompute",
            notebook="differentialExpressionNotebook",
            parameters=[],
        ),
    )

    result = await inspect_search("plasmodb", "GenesByRNASeqXDESeq")

    assert "eda_analysis_spec" in result.overview.eda_guidance
    assert "create_eda_step" in result.overview.eda_guidance
    assert "run_eda_compute" in result.overview.eda_guidance


async def test_inspecting_a_subset_backed_search_carries_the_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subset search reaches the overview too, and names no compute."""
    _stub_definition(
        monkeypatch,
        _search(
            name="GenesByPhenotypeEdaSubset_X",
            params=["eda_dataset_id", "eda_analysis_spec"],
            query="GenesByEdaSubsetGeneric",
            parameters=[],
        ),
    )

    result = await inspect_search("plasmodb", "GenesByPhenotypeEdaSubset_X")

    assert "set_eda_filters" in result.overview.eda_guidance
    assert "create_eda_step" in result.overview.eda_guidance
    assert "run_eda_compute" not in result.overview.eda_guidance


async def test_inspecting_a_plain_search_carries_no_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_definition(
        monkeypatch,
        _search(name="GenesByText", params=["text_search_organism"], parameters=[]),
    )

    result = await inspect_search("plasmodb", "GenesByText")

    assert result.overview.eda_guidance == ""


class TestTheUploadSentinelVocabulary:
    """A one-term vocabulary whose display starts with 'Upload a' is an empty state."""

    @pytest.mark.parametrize(
        ("pairs", "expected"),
        [
            (
                (
                    (
                        "EDAUD_slI5M0RwIg0Zw",
                        "Upload a Phenotype User Dataset in My Workspace",
                    ),
                ),
                True,
            ),
            (
                (
                    (
                        "EDAUD_slI5M0RwIg0Zw",
                        "Upload an RNA-Seq Raw Counts Dataset in My Workspace",
                    ),
                ),
                True,
            ),
            ((("EDAUD_realid", "My RNA-Seq counts"),), False),
            (
                (
                    ("EDAUD_a", "Upload a Phenotype User Dataset in My Workspace"),
                    ("EDAUD_b", "My dataset"),
                ),
                False,
            ),
            ((), False),
            # The article is a whole word, so 'Uploaded' names a dataset.
            ((("EDAUD_x", "Uploaded counts"),), False),
            # The article ends the word, so 'Upload All' names a dataset the user owns.
            ((("EDAUD_x", "Upload All Samples"),), False),
            ((("EDAUD_x", "Upload and merge"),), False),
        ],
    )
    def test_a_flat_vocabulary(
        self, pairs: tuple[tuple[str, str], ...], expected: bool
    ) -> None:
        assert is_upload_sentinel_vocabulary(vocab_terms(*pairs)) is expected

    def test_none_is_not_a_sentinel(self) -> None:
        assert is_upload_sentinel_vocabulary(None) is False

    def test_a_tree_vocabulary_is_never_a_sentinel(self) -> None:
        tree = WDKTreeBoxVocabNode(
            data=WDKVocabNodeData(term="EDAUD_x", display="Upload a Dataset")
        )

        assert is_upload_sentinel_vocabulary(tree) is False
