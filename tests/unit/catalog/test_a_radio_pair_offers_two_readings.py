"""A radio pair offers a term as two readings, never one binding that ORs them."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.domain.parameters import MultiPickValue, SinglePickValue, StringValue
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog import search_inspection, searches
from veupathdb_mcp.catalog.param_formatting import RADIO_OFF
from veupathdb_mcp.catalog.radio_pairs import RadioPair
from veupathdb_mcp.catalog.radio_readings import RadioReadings, radio_readings
from veupathdb_mcp.catalog.search_inspection import read_radio_readings
from veupathdb_mcp.catalog.vocab_lookup import AccessionNames
from veupathdb_mcp.wdk import plan_counts

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "plasmodb_3d7_interpro_vocabulary_half_off.json"
)
SEARCH = "GenesByInterproDomain"
CONTEXT = {"organism": ["Plasmodium falciparum 3D7"], "domain_database": "INTERPRO"}
PAIR = RadioPair(vocabulary="domain_typeahead", free_text="domain_accession")

_PROTEIN_KINASE_LABELS = [
    "IPR011009",
    "IPR050205",
    "IPR011641",
    "IPR050108",
    "IPR051681",
    "IPR030616",
    "IPR051131",
    "IPR045269",
    "IPR016149",
    "IPR050494",
    "IPR051272",
    "IPR050117",
    "IPR045223",
    "IPR050167",
    "IPR051175",
    "IPR051177",
    "IPR050660",
    "IPR050236",
    "IPR050503",
    "IPR051334",
    "IPR052945",
    "IPR013926",
]


def _recorded() -> WDKSearchResponse:
    record = json.loads(FIXTURE.read_text())
    return WDKSearchResponse.model_validate(record["response_json"])


def _serve(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=_recorded())
    client.get_search_details_with_params = AsyncMock(return_value=_recorded())
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda _site: client)
    return client


async def _read(monkeypatch: pytest.MonkeyPatch, term: str) -> list[RadioReadings]:
    _serve(monkeypatch)
    return await read_radio_readings(
        "plasmodb", SEARCH, term, record_type="transcript", context_values=CONTEXT
    )


def _params() -> list[WDKParameter]:
    return list(_recorded().search_data.parameters or [])


class TestTheRecordedInterProVocabulary:
    async def test_the_pair_is_the_one_the_search_declares(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        readings = await _read(monkeypatch, "protein kinase")

        assert [r.pair for r in readings] == [PAIR]

    async def test_the_label_reading_holds_the_entries_whose_label_names_the_term(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (reading,) = await _read(monkeypatch, "protein kinase")

        assert reading.label is not None
        assert reading.label.values == _PROTEIN_KINASE_LABELS
        assert reading.label.params == {
            "domain_typeahead": MultiPickValue(values=_PROTEIN_KINASE_LABELS),
            "domain_accession": StringValue(value=RADIO_OFF),
        }

    async def test_an_entry_its_label_does_not_name_is_left_to_the_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (reading,) = await _read(monkeypatch, "protein kinase")

        assert reading.label is not None
        assert "IPR000719" not in reading.label.values

    async def test_the_description_reading_switches_the_vocabulary_half_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (reading,) = await _read(monkeypatch, "protein kinase")

        assert reading.description is not None
        assert reading.description.text == "*protein kinase*"
        assert reading.description.params == {
            "domain_typeahead": MultiPickValue(values=[RADIO_OFF]),
            "domain_accession": StringValue(value="*protein kinase*"),
        }

    async def test_no_reading_states_both_halves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (reading,) = await _read(monkeypatch, "protein kinase")

        assert reading.label is not None
        assert reading.description is not None
        assert reading.label.params["domain_accession"].to_wire() == RADIO_OFF
        assert reading.description.params["domain_typeahead"].to_wire() == '["N/A"]'

    async def test_the_vocabulary_counts_the_entries_a_name_cannot_reach(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (reading,) = await _read(monkeypatch, "protein kinase")

        assert reading.accession == AccessionNames(
            entries=4717, one_token=1166, nameless=321
        )

    async def test_a_term_no_label_names_keeps_the_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (reading,) = await _read(monkeypatch, "serine threonine kinase catalytic")

        assert reading.label is None
        assert reading.description is not None
        assert reading.description.text == "*serine threonine kinase catalytic*"


def _without_the_off_term(params: list[WDKParameter]) -> list[WDKParameter]:
    def drop(param: WDKParameter) -> WDKParameter:
        match param.vocabulary:
            case [*terms] if param.name == PAIR.vocabulary:
                kept = [term for term in terms if term.term != RADIO_OFF]
                return param.model_copy(update={"vocabulary": kept})
            case _:
                return param

    return [drop(p) for p in params]


def _single_pick(params: list[WDKParameter]) -> list[WDKParameter]:
    return [
        p.model_copy(update={"type": "single-pick-vocabulary"})
        if p.name == PAIR.vocabulary
        else p
        for p in params
    ]


class TestTheShapeDecidesWhatIsOffered:
    def test_a_vocabulary_without_the_off_term_offers_no_description(self) -> None:
        (reading,) = radio_readings(
            [PAIR], _without_the_off_term(_params()), "protein kinase"
        )

        assert reading.description is None
        assert reading.label is not None

    def test_a_single_pick_half_binds_one_label_entry_only(self) -> None:
        (many,) = radio_readings([PAIR], _single_pick(_params()), "protein kinase")
        (one,) = radio_readings([PAIR], _single_pick(_params()), "pkinase_C_6")

        assert many.label is None
        assert many.label_values == _PROTEIN_KINASE_LABELS
        assert one.label is not None
        assert one.label.params["domain_typeahead"] == SinglePickValue(
            value="IPR000961"
        )

    def test_a_pair_missing_from_the_parameters_offers_nothing(self) -> None:
        pair = RadioPair(vocabulary="go_typeahead", free_text="go_term")

        assert radio_readings([pair], _params(), "protein kinase") == []


async def test_each_reading_is_counted_as_its_own_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (reading,) = await _read(monkeypatch, "protein kinase")
    assert reading.description is not None
    client = MagicMock()
    client.run_search_report = AsyncMock(
        return_value=MagicMock(meta=MagicMock(records_returned=lambda: 127))
    )
    monkeypatch.setattr(plan_counts, "get_wdk_client", lambda _site: client)

    count = await plan_counts.count_search_answer(
        "plasmodb", "transcript", SEARCH, reading.description.params
    )

    sent = client.run_search_report.call_args.args[2].parameters
    assert count == 127
    assert sent == {
        "domain_typeahead": '["N/A"]',
        "domain_accession": "*protein kinase*",
    }


async def test_a_name_read_states_the_entries_it_cannot_reach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch)

    info = await search_inspection.read_parameter_options(
        "plasmodb",
        SEARCH,
        PAIR.vocabulary,
        record_type="transcript",
        context_values=CONTEXT,
        narrowing=search_inspection.VocabNarrowing(query="protein kinase"),
    )

    assert info.kind == "parameter_info"
    assert info.allowed_values_note == (
        "1166 of 4717 entries carry a name of one token past their accession, "
        "and 321 of them carry no name, so a lookup by name does not reach them. "
        "An entry no label names can still be on the site."
    )
