from __future__ import annotations

import pytest
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.wdk import WDKParameter, WDKSearch

from veupathdb_mcp.separation import CandidateSource
from veupathdb_mcp.separation.enumerate import CandidateSkippedError, Proposal, bind

_SEARCH = WDKSearch.model_validate(
    {
        "urlSegment": "GenesByRhythm",
        "fullName": "GeneQuestions.GenesByRhythm",
        "displayName": "Genes by rhythm",
        "outputRecordClassName": "transcript",
        "parameters": [
            {
                "name": "period_range",
                "displayName": "Period Range",
                "type": "number-range",
                "isVisible": True,
                "isReadOnly": False,
                "allowEmptyValue": False,
                "min": 20.0,
                "max": 28.0,
                "increment": 0.01,
                "initialDisplayValue": '{"min":"20","max":"28"}',
                "dependentParams": [],
            }
        ],
    }
)


async def _infos(context: dict[str, str]) -> list[WDKParameter]:
    del context
    return _SEARCH.parameters or []


async def test_a_proposal_whose_value_the_kind_cannot_read_is_skipped() -> None:
    proposal = Proposal(
        search_name=_SEARCH.url_segment,
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
        stated={"period_range": "22-26"},
    )

    with pytest.raises(CandidateSkippedError) as skipped:
        await bind(
            _SEARCH, _infos, FilterReadsDouble(), proposal, [], site_id="plasmodb"
        )

    assert skipped.value.reason == "unbound_required"
    assert "period_range" in str(skipped.value.detail)


async def test_a_proposal_that_states_no_range_binds_the_site_default() -> None:
    proposal = Proposal(
        search_name=_SEARCH.url_segment,
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
    )

    bound = await bind(
        _SEARCH, _infos, FilterReadsDouble(), proposal, [], site_id="plasmodb"
    )

    assert bound["period_range"].to_wire() == '{"min": 20.0, "max": 28.0}'


_PICK = WDKSearch.model_validate(
    {
        "urlSegment": "GenesBySnps",
        "fullName": "GeneQuestions.GenesBySnps",
        "displayName": "Genes by SNP class",
        "outputRecordClassName": "transcript",
        "parameters": [
            {
                "name": "snp_class",
                "displayName": "SNP class",
                "type": "single-pick-vocabulary",
                "displayType": "select",
                "isVisible": True,
                "isReadOnly": False,
                "allowEmptyValue": False,
                "initialDisplayValue": "Missense",
                "vocabulary": [
                    ["Missense", "Missense", None],
                    ["Synonymous", "Synonymous", None],
                ],
                "dependentParams": [],
            }
        ],
    }
)


async def test_a_proposal_whose_term_names_no_entry_is_skipped() -> None:
    async def picks(context: dict[str, str]) -> list[WDKParameter]:
        del context
        return _PICK.parameters or []

    proposal = Proposal(
        search_name=_PICK.url_segment,
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
        stated={"snp_class": "non-synonymous"},
    )

    with pytest.raises(CandidateSkippedError) as skipped:
        await bind(_PICK, picks, FilterReadsDouble(), proposal, [], site_id="plasmodb")

    assert skipped.value.reason == "unbound_required"
    assert "non-synonymous" in str(skipped.value.detail)


def _pick(name: str, terms: list[str], dependents: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "displayName": name,
        "type": "single-pick-vocabulary",
        "displayType": "select",
        "isVisible": True,
        "isReadOnly": False,
        "allowEmptyValue": False,
        "vocabulary": [[term, term, None] for term in terms],
        "dependentParams": dependents,
    }


_TWO_PASSES = WDKSearch.model_validate(
    {
        "urlSegment": "GenesByRhythmStage",
        "fullName": "GeneQuestions.GenesByRhythmStage",
        "displayName": "Genes by rhythm and stage",
        "outputRecordClassName": "transcript",
        "parameters": [
            *(_SEARCH.model_dump(by_alias=True)["parameters"]),
            _pick("lineage", ["blood", "liver"], ["stage"]),
            _pick("stage", ["ring", "schizont"], []),
        ],
    }
)


async def test_problems_of_two_passes_skip_the_candidate() -> None:
    async def declared(context: dict[str, str]) -> list[WDKParameter]:
        del context
        return _TWO_PASSES.parameters or []

    proposal = Proposal(
        search_name=_TWO_PASSES.url_segment,
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
        stated={"period_range": "22-26", "lineage": "blood", "stage": "gametocyte"},
    )

    with pytest.raises(CandidateSkippedError) as skipped:
        await bind(
            _TWO_PASSES, declared, FilterReadsDouble(), proposal, [], site_id="plasmodb"
        )

    assert skipped.value.reason == "unbound_required"
    assert "period_range" in str(skipped.value.detail)
    assert "gametocyte" in str(skipped.value.detail)
