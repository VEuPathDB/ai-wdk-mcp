import pytest
from fastmcp.exceptions import ToolError
from tests._support.group_count_site import (
    CountSite,
    install,
    install_recorded_clade_only,
    recorded_taxonomy,
)
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    ParamValue,
    PhyleticExpression,
    PhyleticTree,
    StringValue,
)
from veupathdb.errors import ValidationError
from veupathdb.wdk import WDKStringParam

from veupathdb_mcp.catalog import param_validation
from veupathdb_mcp.catalog.clade_only import (
    CLADE_ONLY_COUNT_REPORTS,
    clade_only_expression,
)
from veupathdb_mcp.tools.catalog_tools import build_clade_only_expression

from .conftest import no_dependent_refresh, validation_callbacks, wdk_search_response

CRYPTOSPORIDIUM = [
    "cand",
    "cbov",
    "choi",
    "chot",
    "chom",
    "chod",
    "cmel",
    "cmtu",
    "cmur",
    "cpia",
    "cpib",
    "cpar",
    "crya",
    "cser",
    "cspi",
    "cscp",
    "ctyz",
    "cubi",
]
GROUPS = 41


def _site(monkeypatch: pytest.MonkeyPatch) -> CountSite:
    return install(monkeypatch, lambda expression: GROUPS)


def _units(expression: str) -> tuple[list[str], list[str]]:
    present, absent = PhyleticExpression.parse(expression).units()
    return list(present.codes), list(absent.codes)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = SearchContext("orthomcl", "group", "GroupsByPhyleticPattern")
    response = wdk_search_response(
        ctx.search_name, [WDKStringParam(name="phyletic_expression")]
    )

    async def _details(
        ctx: SearchContext,
        *,
        resolved_record_type: str,
        parameters: dict[str, ParamValue],
    ) -> param_validation.ResolvedSearch:
        del ctx, resolved_record_type, parameters
        return param_validation.ResolvedSearch(response=response, values_were_read=True)

    async def _taxonomy(site_id: str) -> PhyleticTree:
        assert site_id == "orthomcl"
        return recorded_taxonomy()

    monkeypatch.setattr(param_validation, "resolve_search_details", _details)
    monkeypatch.setattr(
        param_validation, "get_refreshed_dependent_params", no_dependent_refresh
    )
    monkeypatch.setattr(param_validation, "ortho_taxonomy", _taxonomy)


async def _served_value(expression: str) -> str:
    validated = await param_validation.validate_parameters(
        SearchContext("orthomcl", "group", "GroupsByPhyleticPattern"),
        parameters={"phyletic_expression": StringValue(value=expression)},
        callbacks=validation_callbacks(),
    )
    return StringValue.model_validate(validated.params["phyletic_expression"]).value


async def test_a_clade_with_a_code_is_absent_from_every_whole_clade_outside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch)

    result = await clade_only_expression("orthomcl", ["CILI"], None)

    assert result.expression == (
        "CILI>=1T AND ARCH+BACT+APIC+cvel+vbra+AMOE+EUGL+FUNG+META+OEUK+VIRI=0T"
    )
    assert (result.genomes, result.outside, result.groups) == (
        ("ptet", "tetr"),
        855,
        GROUPS,
    )
    assert result.length == len(result.expression)
    assert site.sent == [result.expression]


async def test_a_genus_with_no_clade_code_is_its_genomes_and_the_rest_is_covered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)
    tree = recorded_taxonomy()

    result = await clade_only_expression("orthomcl", CRYPTOSPORIDIUM, None)

    present, absent = _units(result.expression)
    assert present == CRYPTOSPORIDIUM
    assert absent[:4] == ["ARCH", "BACT", "ACON", "bbes"]
    assert absent[-12:] == [
        "gnip",
        "pcga",
        "pcgb",
        "CILI",
        "cvel",
        "vbra",
        "AMOE",
        "EUGL",
        "FUNG",
        "META",
        "OEUK",
        "VIRI",
    ]
    assert ("COCC" in absent, "tgon" in absent, len(absent)) == (False, True, 53)
    assert tree.genomes_under(absent) == tree.genomes_under(["ALL"]) - set(
        CRYPTOSPORIDIUM
    )
    assert (len(result.genomes), result.outside) == (18, 839)


async def test_within_allows_a_larger_clade_and_covers_every_genome_outside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)

    result = await clade_only_expression("orthomcl", ["ecun"], ["MICR"])

    assert result.expression == (
        "ecun>=1T AND ARCH+BACT+ALVE+AMOE+EUGL+ASCO+BASI+CHYT+MUCO+amac+cang+ccor"
        "+rall+META+OEUK+VIRI=0T"
    )
    assert (result.genomes, result.outside) == (("ecun",), 806)


async def test_a_clade_with_no_genome_is_never_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)

    result = await clade_only_expression("orthomcl", ["CHLO"], None)

    assert result.expression == (
        "CHLO>=1T AND ARCH+BACT+ALVE+AMOE+EUGL+FUNG+META+OEUK+CRYP+RHOD+STRE=0T"
    )
    assert "BACI" not in result.expression


async def test_codes_under_a_named_clade_collapse_into_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)

    result = await clade_only_expression("orthomcl", ["APIC", "pfal"], None)

    assert _units(result.expression)[0] == ["APIC"]
    assert len(result.genomes) == 139


async def test_the_recorded_counts_answer_the_built_expressions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install_recorded_clade_only(monkeypatch)

    counted = [
        (await clade_only_expression("orthomcl", clade, within)).groups
        for clade, within in (
            (["ecun"], ["MICR"]),
            (["APIC"], None),
            (CRYPTOSPORIDIUM, None),
        )
    ]

    assert counted == [558, 54039, 1511]
    assert len(site.sent) == 3


@pytest.mark.usefixtures("served")
@pytest.mark.parametrize(
    ("clade", "within"),
    [
        (["CILI"], None),
        (CRYPTOSPORIDIUM, None),
        (["ecun"], ["MICR"]),
        (["APIC", "pfal"], None),
        (["CHLO"], None),
    ],
)
async def test_the_served_validator_takes_each_expression_as_built(
    monkeypatch: pytest.MonkeyPatch, clade: list[str], within: list[str] | None
) -> None:
    _site(monkeypatch)

    result = await clade_only_expression("orthomcl", clade, within)

    assert await _served_value(result.expression) == result.expression


@pytest.mark.parametrize(
    ("clade", "within", "selects", "rejects"),
    [
        (
            ["CILI"],
            None,
            ({"ptet": 1}, {"ptet": 2, "tetr": 1}),
            ({"ptet": 1, "bant": 1}, {"tetr": 1, "pfal": 1}, {"bant": 1}, {}),
        ),
        (
            CRYPTOSPORIDIUM,
            None,
            ({"cpar": 1}, {"chom": 3, "cmur": 1}),
            ({"cpar": 1, "tgon": 1}, {"cpar": 1, "hsap": 2}, {"tgon": 1}, {}),
        ),
        (
            ["ecun"],
            ["MICR"],
            ({"ecun": 1}, {"ecun": 2, "aalp": 1}),
            ({"aalp": 1}, {"ecun": 1, "scer": 1}, {"ecun": 1, "hsap": 1}, {}),
        ),
    ],
)
async def test_the_expression_selects_presence_only_inside(
    monkeypatch: pytest.MonkeyPatch,
    clade: list[str],
    within: list[str] | None,
    selects: tuple[dict[str, int], ...],
    rejects: tuple[dict[str, int], ...],
) -> None:
    _site(monkeypatch)
    tree = recorded_taxonomy()

    result = await clade_only_expression("orthomcl", clade, within)

    expression = PhyleticExpression.parse(result.expression)
    assert [expression.holds_for(group, tree) for group in selects] == [True] * len(
        selects
    )
    assert [expression.holds_for(group, tree) for group in rejects] == [False] * len(
        rejects
    )


@pytest.mark.parametrize(
    ("clade", "within", "named"),
    [
        (["nope"], None, "'nope'"),
        ([], None, "names no code"),
        (["BACI"], None, "holds no genome"),
        (["ARCH", "BACT", "EUKA"], None, "no genome lies outside"),
        (["APIC"], ["HAEM"], "L>=1T AND M=0T"),
    ],
)
async def test_a_clade_the_builder_cannot_state_is_refused_before_any_report(
    monkeypatch: pytest.MonkeyPatch,
    clade: list[str],
    within: list[str] | None,
    named: str,
) -> None:
    site = _site(monkeypatch)

    with pytest.raises(ValidationError) as refused:
        await clade_only_expression("orthomcl", clade, within)

    assert named in (refused.value.detail or "")
    assert site.sent == []


async def test_one_count_report_is_the_whole_request_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch)

    await clade_only_expression("orthomcl", ["ecun"], ["MICR"])

    assert len(site.sent) == CLADE_ONLY_COUNT_REPORTS == 1


async def test_the_served_tool_takes_the_larger_clade_as_within(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)

    result = await build_clade_only_expression("orthomcl", ["ecun"], within=["MICR"])

    assert result.outside == 806


async def test_the_served_tool_turns_a_refusal_into_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)

    with pytest.raises(ToolError, match="no genome lies outside"):
        await build_clade_only_expression("orthomcl", ["ARCH", "BACT", "EUKA"])
