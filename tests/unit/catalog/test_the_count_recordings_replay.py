from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter
from tests._support.group_count_site import install
from veupathdb import JSONObject
from veupathdb.domain.parameters import PhyleticExpression, PhyleticTree
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKAnswer, ortho_taxonomy_of

from veupathdb_mcp.catalog import PhyleticPattern, write_phyletic_expression
from veupathdb_mcp.testing import ORTHOMCL_COUNTS


class _Report(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    expression: str
    total: int


class _Recording(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    reports: tuple[_Report, ...]


type Reading = frozenset[frozenset[tuple[frozenset[str], str, int, bool]]]


def _tree() -> PhyleticTree:
    tree = ortho_taxonomy_of(
        WDKAnswer.model_validate(load_recorded("orthomcl_taxonomy").body)
    )
    assert tree is not None
    return tree


def _recording(name: str) -> _Recording:
    return _Recording.model_validate_json((ORTHOMCL_COUNTS / name).read_text())


def _reading(expression: str) -> Reading:
    root = PhyleticExpression.parse(expression).site_reading().root
    return frozenset(
        frozenset(
            (frozenset(unit.codes), unit.op, unit.count, unit.taxa)
            for unit in PhyleticExpression(root=term).units()
        )
        for term in root.operands("OR")
    )


def _replayed(recording: _Recording) -> Callable[[str], int]:
    totals = {_reading(report.expression): report.total for report in recording.reports}

    def answer(expression: str) -> int:
        read = _reading(expression)
        assert read in totals, f"unrecorded request: {expression[:200]}"
        return totals[read]

    return answer


def _genus() -> list[str]:
    recorded = _recording("orthomcl_every_species_counts.json").reports[0]
    return [
        code
        for unit in PhyleticExpression.parse(recorded.expression).units()
        for code in unit.codes
    ]


def _codes(*codes: str) -> JSONObject:
    return {"kind": "codes", "codes": list(codes)}


def _more_proteins(left: str, right: str) -> JSONObject:
    return {
        "kind": "compare",
        "left": _codes(left),
        "right": _codes(right),
        "reading": "totals",
        "condition": "more_than",
    }


def _only_inside(inside: list[str], edge: list[str]) -> JSONObject:
    return {
        "kind": "all_of",
        "terms": [
            {
                "kind": "count",
                "of": _codes(*inside),
                "measure": "genomes",
                "condition": "at_least",
                "value": 1,
            },
            {
                "kind": "count",
                "of": {"kind": "all_except", "codes": edge},
                "condition": "absent",
            },
        ],
    }


class _Case(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    pattern: JSONObject
    groups: int
    reads: int


_CASES = (
    _Case(
        file="orthomcl_protein_count_ladder.json",
        pattern=_more_proteins("tgon", "pfal"),
        groups=3896,
        reads=8,
    ),
    _Case(
        file="orthomcl_protein_count_ladder_osat_zmay.json",
        pattern=_more_proteins("osat", "zmay"),
        groups=13354,
        reads=11,
    ),
    _Case(
        file="orthomcl_protein_count_ladder_zmay_osat.json",
        pattern=_more_proteins("zmay", "osat"),
        groups=11130,
        reads=9,
    ),
    _Case(
        file="orthomcl_clade_only_counts.json",
        pattern=_only_inside(["ecun"], ["MICR"]),
        groups=558,
        reads=0,
    ),
    _Case(
        file="orthomcl_clade_only_counts.json",
        pattern=_only_inside(["APIC"], ["APIC"]),
        groups=54039,
        reads=0,
    ),
    _Case(
        file="orthomcl_clade_only_counts.json",
        pattern=_only_inside(_genus(), _genus()),
        groups=1511,
        reads=0,
    ),
    _Case(
        file="orthomcl_every_species_counts.json",
        pattern={
            "kind": "count",
            "of": {"kind": "each_species_of", "codes": _genus()},
            "measure": "share",
            "condition": "at_least",
            "value": 50,
        },
        groups=2505,
        reads=0,
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: f"{case.file}-{case.groups}")
async def test_each_recorded_wire_answers_the_pattern_it_records(
    monkeypatch: pytest.MonkeyPatch, case: _Case
) -> None:
    site = install(monkeypatch, _replayed(_recording(case.file)), _tree())

    result = await write_phyletic_expression(
        "orthomcl", TypeAdapter(PhyleticPattern).validate_python(case.pattern)
    )

    assert (result.groups, result.maximum_reads) == (case.groups, case.reads)
    assert len(site.sent) == case.reads + 1
