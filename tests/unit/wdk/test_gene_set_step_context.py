"""The search context a gene set takes from the single step it was taken from.

The search document is the recorded ``search_genes_by_molecular_weight``
fixture, so the parameter kinds are the ones the live site publishes.
"""

from __future__ import annotations

import json

import pytest
from veupathdb.domain.parameters import MultiPickValue, StringValue
from veupathdb.errors import DataParsingError
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKSearchConfig, WDKSearchResponse, WDKStep

from veupathdb_mcp.wdk import param_decoding
from veupathdb_mcp.wdk.gene_set_steps import _extract_step_search_context

ORGANISM = "Plasmodium falciparum 3D7"
BOOLEAN = "boolean_question_TranscriptRecordClasses_TranscriptRecordClass"
STEP_ID = 227292990
WEIGHT_WIRE = {
    "min_molecular_weight": "50000",
    "max_molecular_weight": "50100",
    "organism": json.dumps([ORGANISM]),
}


class _FakeStrategyAPI:
    """Answers one step, and carries the client attribute the spec read names."""

    client = object()

    def __init__(self, step: WDKStep) -> None:
        self._step = step

    async def find_step(self, step_id: int, user_id: str | None = None) -> WDKStep:
        del step_id, user_id
        return self._step


def _step(search_name: str, parameters: dict[str, str]) -> WDKStep:
    return WDKStep.model_validate(
        {
            "id": STEP_ID,
            "search_name": search_name,
            "search_config": WDKSearchConfig(parameters=parameters),
            "record_class_name": "TranscriptRecordClasses.TranscriptRecordClass",
        }
    )


def _recorded_weight_search() -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(
        load_recorded("search_genes_by_molecular_weight").json_body()
    )


@pytest.fixture
def spec_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serve the recorded search document and record every read of it."""
    reads: list[str] = []

    async def _read(
        client: object,
        record_type: str,
        search_name: str,
        context: dict[str, str],
    ) -> WDKSearchResponse:
        del client, record_type, context
        reads.append(search_name)
        return _recorded_weight_search()

    monkeypatch.setattr(param_decoding, "get_search_params_under_context", _read)
    return reads


@pytest.fixture
def unreadable_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _read(
        client: object,
        record_type: str,
        search_name: str,
        context: dict[str, str],
    ) -> WDKSearchResponse:
        del client, record_type, search_name, context
        msg = "the search document is unreachable"
        raise DataParsingError(msg)

    monkeypatch.setattr(param_decoding, "get_search_params_under_context", _read)


@pytest.mark.usefixtures("spec_reads")
async def test_a_single_step_search_carries_its_decoded_parameters() -> None:
    api = _FakeStrategyAPI(_step("GenesByMolecularWeight", WEIGHT_WIRE))

    search_name, record_type, parameters = await _extract_step_search_context(
        api, STEP_ID, None
    )

    assert search_name == "GenesByMolecularWeight"
    assert record_type == "transcript"
    assert parameters == {
        "min_molecular_weight": StringValue(value="50000"),
        "max_molecular_weight": StringValue(value="50100"),
        "organism": MultiPickValue(values=[ORGANISM]),
    }


@pytest.mark.usefixtures("spec_reads")
async def test_a_step_that_sets_no_parameter_reports_an_empty_mapping() -> None:
    """An empty mapping and a missing one say different things to the caller."""
    api = _FakeStrategyAPI(_step("GenesByMolecularWeight", {}))

    _, _, parameters = await _extract_step_search_context(api, STEP_ID, None)

    assert parameters == {}


@pytest.mark.usefixtures("unreadable_spec")
async def test_a_step_whose_spec_cannot_be_read_still_names_its_search() -> None:
    api = _FakeStrategyAPI(_step("GenesByMolecularWeight", WEIGHT_WIRE))

    search_name, record_type, parameters = await _extract_step_search_context(
        api, STEP_ID, None
    )

    assert search_name == "GenesByMolecularWeight"
    assert record_type == "transcript"
    assert parameters is None


async def test_a_boolean_step_reports_no_search_and_reads_no_spec(
    spec_reads: list[str],
) -> None:
    api = _FakeStrategyAPI(_step(BOOLEAN, {"bq_operator": "INTERSECT"}))

    search_name, record_type, parameters = await _extract_step_search_context(
        api, STEP_ID, None
    )

    assert search_name is None
    assert record_type == "transcript"
    assert parameters is None
    assert spec_reads == []


@pytest.mark.usefixtures("spec_reads")
async def test_a_record_type_the_caller_states_is_kept() -> None:
    api = _FakeStrategyAPI(_step("GenesByMolecularWeight", WEIGHT_WIRE))

    _, record_type, _ = await _extract_step_search_context(api, STEP_ID, "gene")

    assert record_type == "gene"
