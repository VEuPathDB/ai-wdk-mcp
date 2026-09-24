"""Which searches a separation can intersect with a gene list, on recorded bodies."""

import pytest
from tests._support.recorded_searches import (
    analysis_backed_search,
    gene_list_search,
    recorded_search,
)
from veupathdb.domain.parameters import MultiPickValue
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog import ParameterInfo, format_param_info_typed
from veupathdb_mcp.separation import CandidateSource
from veupathdb_mcp.separation.eligibility import (
    organism_overrides,
    params_skip,
    search_skip,
)
from veupathdb_mcp.separation.enumerate import CandidateSkippedError, Proposal, bind

FALCIPARUM = "Plasmodium falciparum 3D7"


def _search(name: str) -> WDKSearch:
    return recorded_search(name).search_data


def _infos(search: WDKSearch) -> list[ParameterInfo]:
    return format_param_info_typed(search.parameters or [])


def _recorded_fetch(search: WDKSearch):
    async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
        del context
        return _infos(search)

    return fetch_at


def _catalog_proposal(search: WDKSearch) -> Proposal:
    return Proposal(
        search_name=search.url_segment,
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
    )


def test_an_ortholog_transform_is_a_transform() -> None:
    assert search_skip(_search("search_genes_by_orthologs")) == "transform"


def test_the_boolean_search_is_a_transform() -> None:
    """Its two answer parameters take input steps."""
    assert search_skip(_search("search_boolean_transcript")) == "transform"


def test_a_molecular_weight_search_is_eligible() -> None:
    search = _search("search_genes_by_molecular_weight")

    assert search_skip(search) is None
    assert params_skip(_infos(search)) is None


def test_an_analysis_backed_search_needs_an_analysis() -> None:
    assert search_skip(analysis_backed_search().search_data) == "needs_an_analysis"


def test_the_locus_tag_search_takes_a_gene_list() -> None:
    search = gene_list_search().search_data

    assert search_skip(search) is None
    assert params_skip(_infos(search)) == "takes_a_gene_list"


def test_the_organism_binds_by_vocabulary() -> None:
    infos = _infos(_search("search_genes_by_molecular_weight"))

    assert organism_overrides(infos, [FALCIPARUM]) == {"organism": [FALCIPARUM]}
    assert organism_overrides(infos, [FALCIPARUM, "Toxoplasma gondii ME49"]) == {}


async def test_a_search_that_binds_from_the_organism_alone_is_bound() -> None:
    search = _search("search_genes_by_molecular_weight")

    parameters = await bind(
        search, _recorded_fetch(search), _catalog_proposal(search), [FALCIPARUM]
    )

    assert parameters["organism"] == MultiPickValue(values=[FALCIPARUM])
    assert sorted(parameters) == [
        "max_molecular_weight",
        "min_molecular_weight",
        "organism",
    ]


async def test_a_binding_that_leaves_an_open_slot_is_unbound_required() -> None:
    """The recorded vocabulary holds no Toxoplasma organism, so none binds."""
    search = _search("search_genes_by_molecular_weight")

    with pytest.raises(CandidateSkippedError) as skipped:
        await bind(
            search,
            _recorded_fetch(search),
            _catalog_proposal(search),
            ["Toxoplasma gondii ME49"],
        )

    assert skipped.value.reason == "unbound_required"
    assert skipped.value.detail == "organism"
