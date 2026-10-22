import re
from collections.abc import Callable

import pytest
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict
from tests._support.group_count_site import (
    install,
    install_recorded,
    install_replay,
    recorded_ladder,
    recorded_taxonomy,
    recording,
)
from veupathdb.domain.parameters import PhyleticExpression, check_expression
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog.protein_comparison import (
    MAX_COUNT_REPORTS,
    compare_protein_counts,
)
from veupathdb_mcp.tools.catalog_tools import build_protein_count_comparison

RECORDED_PROBES = [
    "pfal>=128",
    "pfal>=64",
    "pfal>=96",
    "pfal>=112",
    "pfal>=104",
    "pfal>=108",
    "pfal>=110",
    "pfal>=111",
]


def test_the_recording_is_the_measured_bisection_and_both_ladders() -> None:
    recording = recorded_ladder()

    assert (recording.site, recording.build) == ("orthomcl", "8.2")
    assert [report.expression for report in recording.reports[:8]] == RECORDED_PROBES
    assert [report.total for report in recording.reports] == [
        0,
        2,
        1,
        0,
        1,
        1,
        1,
        1,
        3896,
        1472,
    ]


async def test_k_is_read_by_bisection_over_count_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install_recorded(monkeypatch)

    result = await compare_protein_counts("orthomcl", "tgon", "pfal", reverse=False)

    assert result.k == 111
    assert site.sent[:8] == RECORDED_PROBES
    assert result.count_reports == 9
    assert len(site.sent) == 9


async def test_the_ladder_counts_the_recorded_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_recorded(monkeypatch)

    result = await compare_protein_counts("orthomcl", "tgon", "pfal", reverse=False)

    (ladder,) = result.ladders
    assert (ladder.more, ladder.fewer, ladder.groups) == ("tgon", "pfal", 3896)
    assert ladder.expression.startswith("pfal=0 AND tgon>=1 OR pfal=1 AND tgon>=2 OR")
    assert ladder.expression.endswith("OR pfal=111 AND tgon>=112")
    assert "(" not in ladder.expression
    assert ladder.length == 2690


async def test_the_reverse_ladder_stops_where_the_fewer_genome_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install_recorded(monkeypatch)

    result = await compare_protein_counts("orthomcl", "tgon", "pfal", reverse=True)

    forward, reverse = result.ladders
    assert forward.groups == 3896
    assert (reverse.more, reverse.fewer, reverse.groups) == ("pfal", "tgon", 1472)
    assert reverse.expression.startswith("tgon=0 AND pfal>=1 OR")
    assert reverse.expression.endswith("OR tgon=110 AND pfal>=111")
    assert reverse.length == 2664
    assert result.count_reports == len(site.sent) == 10


async def test_every_report_is_a_count_sent_one_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install_recorded(monkeypatch)

    await compare_protein_counts("orthomcl", "tgon", "pfal", reverse=True)

    assert site.most_in_flight == 1


async def test_the_ladder_passes_the_served_check_and_reads_the_measured_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_recorded(monkeypatch)
    tree = recorded_taxonomy()

    result = await compare_protein_counts("orthomcl", "tgon", "pfal", reverse=False)

    expression = PhyleticExpression.parse(result.ladders[0].expression)
    check_expression(expression, tree)
    held = [
        expression.holds_for(group, tree)
        for group in (
            {"tgon": 25, "pfal": 15},
            {"tgon": 32, "pfal": 24},
            {"tgon": 1},
            {"tgon": 1, "pfal": 1},
            {"pfal": 1},
        )
    ]
    assert held == [True, True, True, False, False]


@pytest.mark.parametrize(
    ("genome_a", "genome_b", "named"),
    [
        ("APIC", "pfal", "'APIC' is not one genome"),
        ("tgon", "nope", "'nope' is not one genome"),
        ("tgon", "tgon", "name the same genome"),
    ],
)
async def test_a_code_that_is_not_one_other_genome_is_refused_before_any_report(
    monkeypatch: pytest.MonkeyPatch, genome_a: str, genome_b: str, named: str
) -> None:
    site = install_recorded(monkeypatch)

    with pytest.raises(ValidationError) as refused:
        await compare_protein_counts("orthomcl", genome_a, genome_b, reverse=False)

    assert named in (refused.value.detail or "")
    assert site.sent == []


def _largest_is(top: int, other: int) -> Callable[[str], int]:
    def answer(expression: str) -> int:
        probe = re.fullmatch(r"pfal>=(\d+)", expression)
        if probe is None:
            return other
        return 1 if int(probe[1]) <= top else 0

    return answer


async def test_the_widest_count_takes_the_named_bound_of_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, _largest_is(1023, 5))

    result = await compare_protein_counts("orthomcl", "tgon", "pfal", reverse=True)

    assert result.k == 1023
    assert result.count_reports == len(site.sent) == MAX_COUNT_REPORTS == 15


async def test_a_genome_with_no_protein_in_any_group_has_k_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, _largest_is(0, 0))

    result = await compare_protein_counts("orthomcl", "tgon", "pfal", reverse=True)

    assert result.k == 0
    assert [ladder.expression for ladder in result.ladders] == [
        "pfal=0 AND tgon>=1",
        "tgon=0 AND pfal>=1",
    ]
    assert site.sent[-3:] == ["pfal>=1", "pfal=0 AND tgon>=1", "tgon=0 AND pfal>=1"]


async def test_a_count_past_the_last_probe_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, _largest_is(10**9, 5))

    with pytest.raises(ValidationError) as refused:
        await compare_protein_counts("orthomcl", "tgon", "pfal", reverse=False)

    assert "pfal holds 1024 or more proteins in one group" in (
        refused.value.detail or ""
    )
    assert site.sent == ["pfal>=128", "pfal>=256", "pfal>=512", "pfal>=1024"]


class _LargeFamily(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    genome_a: str
    genome_b: str
    k: int
    groups: tuple[int, int]
    lengths: tuple[int, int]


_LARGE_FAMILIES = (
    _LargeFamily(
        name="orthomcl_protein_count_ladder_osat_zmay.json",
        genome_a="osat",
        genome_b="zmay",
        k=340,
        groups=(13354, 11130),
        lengths=(8644, 8618),
    ),
    _LargeFamily(
        name="orthomcl_protein_count_ladder_zmay_osat.json",
        genome_a="zmay",
        genome_b="osat",
        k=212,
        groups=(11130, 13354),
        lengths=(5316, 5290),
    ),
)


@pytest.mark.parametrize("case", _LARGE_FAMILIES, ids=lambda case: case.name)
async def test_a_large_family_reads_the_recorded_k_and_both_ladders(
    monkeypatch: pytest.MonkeyPatch, case: _LargeFamily
) -> None:
    recorded = recording(case.name)
    site = install_replay(monkeypatch, recorded)

    result = await compare_protein_counts(
        "orthomcl", case.genome_a, case.genome_b, reverse=True
    )

    assert result.k == case.k
    assert tuple(ladder.groups for ladder in result.ladders) == case.groups
    assert tuple(ladder.length for ladder in result.ladders) == case.lengths
    assert len(site.sent) == result.count_reports == len(recorded.reports)


async def test_the_served_tool_turns_a_refusal_into_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_recorded(monkeypatch)

    with pytest.raises(ToolError, match="'APIC' is not one genome"):
        await build_protein_count_comparison("orthomcl", "APIC", "pfal")
