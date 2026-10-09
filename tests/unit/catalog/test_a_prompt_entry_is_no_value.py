"""An entry a site ships as the prompt of a vocabulary is not a value: the list
never offers it, and a value equal to it is a placeholder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKEnumParam, WDKSearchResponse

from veupathdb_mcp.catalog import search_inspection, searches
from veupathdb_mcp.catalog.param_formatting import (
    ParamDependencies,
    ParameterInfo,
    format_param_info_typed,
    format_typed_param,
)
from veupathdb_mcp.catalog.search_inspection import (
    VocabNarrowing,
    read_parameter_options,
)

from .conftest import vocab_terms

_CHOOSE = "Choose chromosome"


def _location() -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(
        load_recorded("search_genes_by_location").json_body()
    )


def _chromosome() -> ParameterInfo:
    infos = format_param_info_typed(_location().search_data.parameters or [])
    return next(info for info in infos if info.name == "chromosomeOptional")


def _values(info: ParameterInfo) -> list[str]:
    return [option.value for option in info.allowed_values or []]


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_location.json"), reason=NEEDS_QA_RECORDING
)
def test_the_chromosome_prompt_is_not_offered() -> None:
    chromosome = _chromosome()

    assert chromosome.default_value == _CHOOSE
    assert _CHOOSE not in _values(chromosome)
    assert _CHOOSE not in [option.value for option in chromosome.vocabulary()]
    assert _values(chromosome)[:2] == ["01", "02"]
    assert chromosome.prompt_values == [_CHOOSE]


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_location.json"), reason=NEEDS_QA_RECORDING
)
def test_the_chromosome_prompt_is_a_placeholder_and_a_chromosome_is_not() -> None:
    chromosome = _chromosome()

    assert chromosome.is_placeholder(_CHOOSE)
    assert not chromosome.is_placeholder("01")


def test_a_prompt_whose_term_is_an_id_is_read_by_its_label() -> None:
    """The user-dataset and module vocabularies ship a prompt row whose term is
    a dummy id and whose label asks for a choice."""
    param = WDKEnumParam(
        name="gene_list_dataset",
        type="single-pick-vocabulary",
        vocabulary=vocab_terms(
            ("bla", "Choose a public or private Gene List User Dataset"),
            ("1_choose_module", "Choose a Module"),
            ("0", "--None--"),
            ("123456", "My kinase list"),
        ),
    )

    info = format_typed_param(param, ParamDependencies())

    assert _values(info) == ["123456"]
    assert info.prompt_values == ["bla", "1_choose_module", "0"]
    assert info.is_placeholder("bla")


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_location.json"), reason=NEEDS_QA_RECORDING
)
async def test_a_narrowed_read_matches_no_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _location()
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=response)
    client.get_search_details_with_params = AsyncMock(return_value=response)
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda _site: client)

    info = await read_parameter_options(
        "plasmodb",
        "GenesByLocation",
        "chromosomeOptional",
        record_type="transcript",
        context_values={"organismSinglePick": "Plasmodium falciparum 3D7"},
        narrowing=VocabNarrowing(query="chromosome"),
    )

    assert info.kind == "parameter_info"
    assert info.allowed_values is None
    assert info.vocab_lookup is not None
    assert info.vocab_lookup.matches == []
