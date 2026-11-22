from __future__ import annotations

import pytest
from pydantic import JsonValue, TypeAdapter
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain.parameters import (
    FAKE_ALL_SENTINEL,
    FilterStatementError,
    FilterValue,
    MultiPickValue,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog import read_under_parents
from veupathdb_mcp.catalog.param_dag import ParamFetcher, UnreadStatementError

from .test_a_stated_value_is_read_once import by_organism

_DECLARATION: TypeAdapter[WDKParameter] = TypeAdapter(WDKParameter)
_VIVAX = "Plasmodium vivax P01"


def _node(term: str, display: str, *children: JsonValue) -> JsonValue:
    return {"data": {"term": term, "display": display}, "children": list(children)}


def _organism(
    *leaves: tuple[str, str], dependents: tuple[str, ...] = ()
) -> WDKParameter:
    return _DECLARATION.validate_python(
        {
            "name": "organism",
            "type": "multi-pick-vocabulary",
            "displayType": "treeBox",
            "dependentParams": list(dependents),
            "vocabulary": _node(
                FAKE_ALL_SENTINEL,
                "All",
                _node("Plasmodium", "Plasmodium", *(_node(*leaf) for leaf in leaves)),
            ),
        }
    )


def _text(name: str) -> WDKParameter:
    return _DECLARATION.validate_python({"name": name, "type": "string"})


def _recording(
    seen: list[dict[str, str]], answer: list[WDKParameter], later: list[WDKParameter]
) -> ParamFetcher:
    async def fetch_at(context: dict[str, str]) -> list[WDKParameter]:
        seen.append(dict(context))
        return answer if len(seen) == 1 else later

    return fetch_at


async def test_a_parent_stated_by_its_label_reaches_the_fetch_as_its_term() -> None:
    declarations = [
        _organism((_VIVAX, "P. vivax P01"), dependents=("strain",)),
        _text("strain"),
    ]
    seen: list[dict[str, str]] = []

    read = await read_under_parents(
        _recording(seen, declarations, declarations),
        {"organism": ["P. vivax P01"], "strain": "x"},
        FilterReadsDouble(),
    )

    assert read["organism"] == MultiPickValue(values=[_VIVAX])
    assert seen[1] == {"organism": f'["{_VIVAX}"]'}


async def test_a_label_matches_its_leaf_and_a_genus_stays_as_stated() -> None:
    organism = _organism(
        (_VIVAX, "P. vivax P01"),
        ("Plasmodium falciparum 3D7", "P. falciparum 3D7"),
    )
    seen: list[dict[str, str]] = []

    read = await read_under_parents(
        _recording(seen, [organism], [organism]),
        {"organism": ["plasmodium vivax p01", "Plasmodium vivax"]},
        FilterReadsDouble(),
    )

    assert read["organism"] == MultiPickValue(values=[_VIVAX, "Plasmodium vivax"])


async def test_a_name_no_later_fetch_declares_is_refused_by_name() -> None:
    seen: list[dict[str, str]] = []
    first = [_organism((_VIVAX, _VIVAX), dependents=("strain",)), _text("strain")]

    with pytest.raises(UnreadStatementError, match="strain"):
        await read_under_parents(
            _recording(seen, first, [first[0]]),
            {"organism": [_VIVAX], "strain": "x"},
            FilterReadsDouble(),
        )

    assert len(seen) <= 6


_RECORDED = pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_ngs_snps.json",
        "wdk/search_genes_by_ngs_snps_under_another_organism.json",
    ),
    reason=NEEDS_QA_RECORDING,
)
_PERU = [{"field": "Dataset", "value": ["WGS of Patient Isolates from Peru"]}]


@_RECORDED
async def test_a_dependent_stated_alone_reads_under_its_bound_parent() -> None:
    read = await read_under_parents(
        by_organism,
        {"variation_sample_meta": _PERU},
        FilterReadsDouble(),
        bound={"organismSinglePick": MultiPickValue(values=[_VIVAX])},
    )

    assert list(read) == ["variation_sample_meta"]
    value = read["variation_sample_meta"]
    assert isinstance(value, FilterValue)
    assert [clause.value for clause in value.filters] == [
        ["WGS of Patient Isolates from Peru"]
    ]


@_RECORDED
async def test_a_dependent_under_another_bound_parent_is_refused() -> None:
    with pytest.raises(FilterStatementError, match="WGS of Patient Isolates from Peru"):
        await read_under_parents(
            by_organism,
            {"variation_sample_meta": _PERU},
            FilterReadsDouble(),
            bound={
                "organismSinglePick": MultiPickValue(
                    values=["Plasmodium falciparum 3D7"]
                )
            },
        )


async def test_a_stated_branch_of_a_leaf_counted_tree_is_read_as_its_leaves() -> None:
    organism = _DECLARATION.validate_python(
        {
            "name": "organism",
            "type": "multi-pick-vocabulary",
            "displayType": "treeBox",
            "countOnlyLeaves": True,
            "vocabulary": _node(
                FAKE_ALL_SENTINEL,
                "All",
                _node(
                    "Plasmodium",
                    "Plasmodium",
                    _node(_VIVAX, _VIVAX),
                    _node("Plasmodium falciparum 3D7", "P. falciparum 3D7"),
                ),
            ),
        }
    )

    async def fetch_at(context: dict[str, str]) -> list[WDKParameter]:
        del context
        return [organism]

    read = await read_under_parents(
        fetch_at, {"organism": ["Plasmodium"]}, FilterReadsDouble()
    )

    assert read == {
        "organism": MultiPickValue(values=[_VIVAX, "Plasmodium falciparum 3D7"])
    }
