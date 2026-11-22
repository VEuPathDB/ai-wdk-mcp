"""A read names every parameter's miss in one refusal, each entry led by its pick."""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter
from tests._support.filter_reads import FilterReadsDouble
from veupathdb import JSONObject
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    DECIDED_CANDIDATES,
    SHOWN_CANDIDATES,
    ParamValue,
    SinglePickValue,
    VocabOption,
    VocabularyEntryError,
    flatten_vocab,
    rank_entries,
)
from veupathdb.errors import ValidationError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKEnumParam, WDKParameter

from veupathdb_mcp.catalog import (
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
    ResolveContext,
    param_validation,
    read_under_parents,
    use_decisions_transport,
)
from veupathdb_mcp.catalog.param_dag import resolve_params_with_intent
from veupathdb_mcp.catalog.param_intent import ParamIntent

from .conftest import (
    no_dependent_refresh,
    serving,
    validation_callbacks,
    wdk_search_response,
)
from .test_a_filter_statement_binds_by_its_facet import (
    ngs_snps,
    variant_characteristics,
)

_PF = ["Plasmodium falciparum 3D7"]
_ABOUT = ResolveContext(site_id="plasmodb")
_RECORDED = needs_qa_recording("wdk/search_genes_by_ngs_snps.json")

_TWO_MISSES: dict[str, JsonValue] = {
    "organismSinglePick": _PF,
    "organism_select_none": _PF,
    "variation_sample_meta": [{"field": "sex", "value": ["female"]}],
    "gene_variant_stats": [{"field": "total_variants", "value": {"min": 4824}}],
}


class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore")
    param: str
    detail: str
    value: JsonValue = None
    candidates: list[VocabOption] | None = None


_ROWS: TypeAdapter[list[_Row]] = TypeAdapter(list[_Row])


def _rows(refusal: ValidationError) -> list[_Row]:
    rows = _ROWS.validate_python(refusal.errors)
    assert all(row.detail and "\n" not in row.detail for row in rows)
    assert refusal.detail == "\n".join(row.detail for row in rows)
    return rows


def _reads() -> FilterReadsDouble:
    return FilterReadsDouble(
        {"total_variants": "ontology_term_summary_total_variants"}, count=1
    )


def _picking_the_last_offered() -> list[DecisionRequest]:
    sent: list[DecisionRequest] = []

    async def send(request: DecisionRequest) -> DecisionResponse:
        sent.append(request)
        [question] = request.questions
        assert isinstance(question, ChoiceQuestion)
        last = question.choices[-2].value
        return DecisionResponse.model_validate(
            {
                "answers": [
                    {
                        "type": "choice",
                        "name": question.name,
                        "choice": last,
                        "probabilities": [{"value": last, "probability": 1.0}],
                        "confidence": 1.0,
                    }
                ]
            }
        )

    use_decisions_transport(send)
    return sent


def _led(options: list[VocabOption], phrase: str) -> list[str]:
    ranked = [c.value for c in rank_entries(options, phrase, DECIDED_CANDIDATES)]
    return [ranked[-1], *ranked[:-1]][:SHOWN_CANDIDATES]


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
class TestAReadUnderParents:
    async def test_two_filter_misses_are_one_refusal(self) -> None:
        with pytest.raises(ValidationError) as refused:
            await read_under_parents(
                serving(*ngs_snps(), *variant_characteristics()),
                _TWO_MISSES,
                _reads(),
                about=_ABOUT,
            )

        rows = _rows(refused.value)
        assert [row.param for row in rows] == [
            "variation_sample_meta",
            "gene_variant_stats",
        ]
        assert "selects 1 " in refused.value.detail
        assert "selects none of it" in refused.value.detail

    async def test_two_unnamed_entries_are_one_ordered_refusal(self) -> None:
        sent = _picking_the_last_offered()
        declarations = ngs_snps()
        options = {d.name: flatten_vocab(d.vocabulary) for d in declarations}

        with pytest.raises(VocabularyEntryError) as refused:
            await read_under_parents(
                serving(*declarations),
                {
                    "organismSinglePick": _PF,
                    "ReadFrequencyPercent": "95 percent",
                    "snp_class": "non-synonymous",
                },
                FilterReadsDouble(),
                about=_ABOUT,
            )

        assert len(sent) == 2
        faults = refused.value.faults
        assert [name for name, _ in faults] == ["ReadFrequencyPercent", "snp_class"]
        for name, resolution in faults:
            shown = [c.value for c in resolution.candidates]
            assert shown[:SHOWN_CANDIDATES] == _led(options[name], resolution.phrase)
        _rows(refused.value)


@pytest.mark.skipif(_RECORDED, reason=NEEDS_QA_RECORDING)
async def test_the_walk_names_two_filter_misses_at_once() -> None:
    with pytest.raises(ValidationError) as refused:
        await resolve_params_with_intent(
            fetch_at=serving(*ngs_snps(), *variant_characteristics()),
            filter_reads=_reads(),
            intent=ParamIntent(),
            search_name="GenesByNgsSnps",
            stated=_TWO_MISSES,
            about=None,
        )

    rows = _rows(refused.value)
    assert [row.param for row in rows] == [
        "variation_sample_meta",
        "gene_variant_stats",
    ]


_ORGANISMS = [
    ["Pf3D7", "P. falciparum 3D7", None],
    ["PfIT", "P. falciparum IT", None],
    ["PvP01", "P. vivax P01", None],
]
_STAGES = [
    ["ring", "Ring stage", None],
    ["rings", "Ring stages", None],
    ["schizont", "Schizont stage", None],
]


def _enum(name: str, vocab: list[list[str | None]]) -> WDKParameter:
    raw: JSONObject = {
        "type": "single-pick-vocabulary",
        "name": name,
        "display_name": name,
        "vocabulary": cast("JsonValue", vocab),
        "dependent_params": [],
        "allow_empty_value": False,
    }
    return WDKEnumParam.model_validate(raw)


@pytest.fixture
def two_picks(monkeypatch: pytest.MonkeyPatch) -> list[WDKParameter]:
    declarations = [_enum("organism", _ORGANISMS), _enum("stage", _STAGES)]
    response = wdk_search_response(
        "GenesByStage", declarations, level="NONE", is_valid=False
    )

    async def resolve(
        ctx: SearchContext, *, resolved_record_type: str, parameters: JSONObject
    ) -> param_validation.ResolvedSearch:
        del ctx, resolved_record_type, parameters
        return param_validation.ResolvedSearch(response=response, values_were_read=True)

    monkeypatch.setattr(param_validation, "resolve_search_details", resolve)
    monkeypatch.setattr(
        param_validation, "get_refreshed_dependent_params", no_dependent_refresh
    )
    return declarations


async def _validated(stated: dict[str, ParamValue]) -> ValidationError:
    with pytest.raises(ValidationError) as refused:
        await param_validation.validate_parameters(
            SearchContext("plasmodb", "transcript", "GenesByStage"),
            stated=stated,
            callbacks=validation_callbacks(),
            about=_ABOUT,
        )
    return refused.value


class TestAValidatedRefusal:
    async def test_every_entry_of_an_entries_only_refusal_is_ordered(
        self, two_picks: list[WDKParameter]
    ) -> None:
        sent = _picking_the_last_offered()
        options = {d.name: flatten_vocab(d.vocabulary) for d in two_picks}

        refusal = await _validated(
            {
                "organism": SinglePickValue(value="Pf3D"),
                "stage": SinglePickValue(value="ring stag"),
            }
        )

        assert isinstance(refusal, VocabularyEntryError)
        assert len(sent) == 2
        rows = _rows(refusal)
        assert [row.param for row in rows] == ["organism", "stage"]
        for row, phrase in zip(rows, ["Pf3D", "ring stag"], strict=True):
            assert row.candidates is not None
            assert [c.value for c in row.candidates] == _led(options[row.param], phrase)

    async def test_a_mixed_refusal_orders_its_entries_and_keeps_the_other_row(
        self, two_picks: list[WDKParameter]
    ) -> None:
        _picking_the_last_offered()
        options = {d.name: flatten_vocab(d.vocabulary) for d in two_picks}

        refusal = await _validated(
            {
                "organism": SinglePickValue(value="Pf3D"),
                "stagee": SinglePickValue(value="ring"),
                "stage": SinglePickValue(value="ring stag"),
            }
        )

        assert not isinstance(refusal, VocabularyEntryError)
        rows = _rows(refusal)
        assert [row.param for row in rows] == ["organism", "stagee", "stage"]
        assert rows[1].candidates is None
        assert "does not exist for this search" in rows[1].detail
        for row, phrase in zip((rows[0], rows[2]), ["Pf3D", "ring stag"], strict=True):
            assert row.candidates is not None
            assert [c.value for c in row.candidates] == _led(options[row.param], phrase)
