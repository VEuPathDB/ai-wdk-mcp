import pytest
from fastmcp.exceptions import ToolError
from scripts.record_orthomcl_every_species import CRYPTOSPORIDIUM
from tests._support.group_count_site import (
    CountSite,
    install,
    install_replay,
    recorded_every_species,
    recorded_taxonomy,
)
from veupathdb.domain.parameters import PhyleticExpression
from veupathdb.errors import ValidationError

from veupathdb_mcp.catalog.clade_only import (
    EVERY_SPECIES_COUNT_REPORTS,
    every_species_expression,
)
from veupathdb_mcp.tools.catalog_tools import build_every_species_expression

EXPRESSION = (
    "cand>=1T AND cbov>=1T AND choi+chot+chom+chod>=2T AND cmel+cmtu>=1T AND "
    "cmur>=1T AND cpia+cpib+cpar>=2T AND crya>=1T AND cser>=1T AND cspi>=1T AND "
    "cscp>=1T AND ctyz>=1T AND cubi>=1T"
)
GROUPS = 41


def _site(monkeypatch: pytest.MonkeyPatch) -> CountSite:
    return install(monkeypatch, lambda expression: GROUPS)


async def test_each_species_is_one_unit_at_half_its_genomes_rounded_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch)

    result = await every_species_expression("orthomcl", CRYPTOSPORIDIUM)

    assert result.expression == EXPRESSION
    assert [(s.species, len(s.genomes), s.present) for s in result.species][:6] == [
        ("Cryptosporidium andersoni", 1, 1),
        ("Cryptosporidium bovis", 1, 1),
        ("Cryptosporidium hominis", 4, 2),
        ("Cryptosporidium meleagridis", 2, 1),
        ("Cryptosporidium muris", 1, 1),
        ("Cryptosporidium parvum", 3, 2),
    ]
    assert len(result.species) == 12
    assert result.genomes == tuple(sorted(CRYPTOSPORIDIUM))
    assert (result.groups, result.length) == (GROUPS, len(EXPRESSION))
    assert site.sent == [EXPRESSION]


async def test_the_units_name_every_genome_of_the_clade_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)

    result = await every_species_expression("orthomcl", CRYPTOSPORIDIUM)

    units = PhyleticExpression.parse(result.expression).units()
    assert sorted(code for unit in units for code in unit.codes) == sorted(
        CRYPTOSPORIDIUM
    )
    assert {(unit.op, unit.taxa) for unit in units} == {(">=", True)}
    assert [unit.count for unit in units] == [s.present for s in result.species]
    assert " OR " not in result.expression


async def test_a_clade_code_is_read_as_its_genomes_by_species(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)
    tree = recorded_taxonomy()

    result = await every_species_expression("orthomcl", ["CILI"])

    assert result.expression == "ptet>=1T AND tetr>=1T"
    assert set(result.genomes) == tree.genomes_under(["CILI"])


@pytest.mark.parametrize(
    ("clade", "named"),
    [
        (["NOPE"], "codes the site's taxonomy does not hold: ['NOPE']"),
        ([], "clade names no code"),
        (["choi", "chot"], "one species, Cryptosporidium hominis"),
        (["pfal"], "one species, Plasmodium falciparum"),
    ],
)
async def test_an_unknown_clade_or_a_single_species_is_refused_unsent(
    monkeypatch: pytest.MonkeyPatch, clade: list[str], named: str
) -> None:
    site = _site(monkeypatch)

    with pytest.raises(ValidationError) as refused:
        await every_species_expression("orthomcl", clade)

    assert named in (refused.value.detail or "")
    assert site.sent == []


async def test_one_count_report_is_the_whole_request_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch)

    await every_species_expression("orthomcl", CRYPTOSPORIDIUM)

    assert len(site.sent) == EVERY_SPECIES_COUNT_REPORTS == 1


async def test_the_recorded_cryptosporidium_count_is_the_built_expressions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = recorded_every_species()
    install_replay(monkeypatch, recorded)

    result = await build_every_species_expression("orthomcl", CRYPTOSPORIDIUM)

    assert (recorded.site, recorded.search) == ("orthomcl", "GroupsByPhyleticPattern")
    assert [report.expression for report in recorded.reports] == [EXPRESSION]
    assert (recorded.build, result.groups) == ("8.2", 2505)
    assert result.groups == recorded.reports[0].total


async def test_the_served_tool_turns_a_refusal_into_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)

    with pytest.raises(ToolError, match="one species"):
        await build_every_species_expression("orthomcl", ["choi", "chot"])
