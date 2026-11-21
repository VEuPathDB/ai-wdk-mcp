from __future__ import annotations

import pytest
from pydantic import JsonValue, TypeAdapter
from veupathdb.domain.parameters import FAKE_ALL_SENTINEL, MultiPickValue
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog import read_under_parents
from veupathdb_mcp.catalog.param_dag import ParamFetcher, UnreadStatementError

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
    )

    assert read["organism"] == MultiPickValue(values=[_VIVAX, "Plasmodium vivax"])


async def test_a_name_no_later_fetch_declares_is_refused_by_name() -> None:
    seen: list[dict[str, str]] = []
    first = [_organism((_VIVAX, _VIVAX), dependents=("strain",)), _text("strain")]

    with pytest.raises(UnreadStatementError, match="strain"):
        await read_under_parents(
            _recording(seen, first, [first[0]]),
            {"organism": [_VIVAX], "strain": "x"},
        )

    assert len(seen) <= 6
