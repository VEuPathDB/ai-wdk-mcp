"""A site's prompt text and the radio pair's off value are placeholders, not criteria,
decided on the parameter's info from the recorded sheets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests._support.recordings import TEST_ROOT
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog.param_formatting import (
    RADIO_OFF,
    ParameterInfo,
    format_param_info_typed,
)

_SEPARATION_FIXTURES = Path(__file__).parents[1] / "separation" / "fixtures"


def _sheet_of(response: WDKSearchResponse) -> dict[str, ParameterInfo]:
    infos = format_param_info_typed(response.search_data.parameters or [])
    return {info.name: info for info in infos}


def _recorded(name: str) -> dict[str, ParameterInfo]:
    return _sheet_of(WDKSearchResponse.model_validate(load_recorded(name).json_body()))


def _go_term_sheet() -> dict[str, ParameterInfo]:
    body = json.loads((_SEPARATION_FIXTURES / "search_go_term.json").read_text())
    return _sheet_of(WDKSearchResponse.model_validate(body.get("body", body)))


@pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_location.json"), reason=NEEDS_QA_RECORDING
)
def test_an_example_the_site_prints_is_a_placeholder() -> None:
    sequence = _recorded("search_genes_by_location")["sequenceId"]

    assert sequence.default_value == "(Example: Pf3D7_04_v3)"
    assert sequence.is_placeholder(sequence.default_value)


@pytest.mark.skipif(
    needs_qa_recording(TEST_ROOT / "unit/separation/fixtures/search_go_term.json"),
    reason=NEEDS_QA_RECORDING,
)
def test_the_off_value_a_radio_half_publishes_is_a_placeholder() -> None:
    go_term = _go_term_sheet()["go_term"]

    assert go_term.default_value == RADIO_OFF
    assert go_term.is_placeholder(RADIO_OFF)
    assert go_term.is_placeholder(" n/a ")


@pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_location.json",
        TEST_ROOT / "unit/separation/fixtures/search_go_term.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
def test_a_value_a_researcher_types_is_no_placeholder() -> None:
    sequence = _recorded("search_genes_by_location")["sequenceId"]
    go_term = _go_term_sheet()["go_term"]

    assert not sequence.is_placeholder("Pf3D7_04_v3")
    assert not go_term.is_placeholder("GO:0003723")


def test_a_vocabulary_term_is_never_a_placeholder() -> None:
    """A term the vocabulary offers is a value the site accepts, whatever it reads."""
    info = ParameterInfo.model_validate(
        {
            "name": "status",
            "display_name": "Status",
            "type": "single-pick-vocabulary",
            "required": True,
            "is_visible": True,
            "help": "",
            "value_format": "",
            "allowed_values": [{"value": RADIO_OFF, "display": "not applicable"}],
        }
    )

    assert not info.is_placeholder(RADIO_OFF)
