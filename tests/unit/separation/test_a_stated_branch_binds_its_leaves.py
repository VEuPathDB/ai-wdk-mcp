from __future__ import annotations

from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain.parameters import MultiPickValue
from veupathdb.wdk import WDKParameter, WDKSearch

from veupathdb_mcp.separation import CandidateSource
from veupathdb_mcp.separation.enumerate import Proposal, bind


def _node(term: str, *children: dict[str, object]) -> dict[str, object]:
    return {"data": {"term": term, "display": term}, "children": list(children)}


_SEARCH = WDKSearch.model_validate(
    {
        "urlSegment": "GenesByTaxon",
        "fullName": "GeneQuestions.GenesByTaxon",
        "displayName": "Organism",
        "outputRecordClassName": "transcript",
        "parameters": [
            {
                "name": "organism",
                "displayName": "Organism",
                "type": "multi-pick-vocabulary",
                "displayType": "treeBox",
                "isVisible": True,
                "isReadOnly": False,
                "allowEmptyValue": False,
                "countOnlyLeaves": True,
                "minSelectedCount": 1,
                "initialDisplayValue": "[]",
                "dependentParams": [],
                "vocabulary": _node(
                    "@@fake@@",
                    _node(
                        "Plasmodiidae",
                        _node("P. falciparum 3D7"),
                        _node("P. vivax P01"),
                    ),
                ),
            }
        ],
    }
)


async def _infos(context: dict[str, str]) -> list[WDKParameter]:
    del context
    return _SEARCH.parameters or []


async def test_a_stated_branch_is_bound_as_its_leaves() -> None:
    proposal = Proposal(
        search_name=_SEARCH.url_segment,
        source=CandidateSource.CATALOG,
        basis="the site's catalog",
        stated={"organism": ["Plasmodiidae"]},
    )

    bound = await bind(
        _SEARCH, _infos, FilterReadsDouble(), proposal, [], site_id="plasmodb"
    )

    assert bound["organism"] == MultiPickValue(
        values=["P. falciparum 3D7", "P. vivax P01"]
    )
