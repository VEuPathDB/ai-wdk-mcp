from __future__ import annotations

import pytest
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog import ParameterInfo, format_param_info_typed
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


async def _infos(context: dict[str, str]) -> list[ParameterInfo]:
    del context
    return format_param_info_typed(_SEARCH.parameters or [])


async def test_a_proposal_whose_value_the_kind_cannot_read_is_skipped() -> None:
    proposal = Proposal(
        search_name=_SEARCH.url_segment,
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
        stated={"period_range": "22-26"},
    )

    with pytest.raises(CandidateSkippedError) as skipped:
        await bind(_SEARCH, _infos, proposal, [])

    assert skipped.value.reason == "unbound_required"
    assert "period_range" in str(skipped.value.detail)


async def test_a_proposal_that_states_no_range_binds_the_site_default() -> None:
    proposal = Proposal(
        search_name=_SEARCH.url_segment,
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
    )

    bound = await bind(_SEARCH, _infos, proposal, [])

    assert bound["period_range"].to_wire() == '{"min": 20.0, "max": 28.0}'
