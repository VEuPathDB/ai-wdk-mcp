import asyncio
import re
from collections.abc import Callable
from typing import TypeVar

import pytest
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import to_jsonable_python
from tests._support.group_count_site import CountSite, install
from tests._support.phyletic_truth import (
    holds,
    site_counts,
    synthetic_groups,
    synthetic_tree,
    wide_tree,
)
from veupathdb import JSONObject
from veupathdb.domain.parameters import PhyleticExpression, check_expression
from veupathdb.errors import ValidationError, WDKError

from veupathdb_mcp.catalog import (
    CHARACTERS_WITHIN_READ_TIMEOUT,
    MAX_EXPRESSION_TERMS,
    CountTerm,
    PhyleticExpressionResult,
    PhyleticExpressionTooLargeError,
    PhyleticExpressionTooSlowError,
    PhyleticPattern,
    phyletic_builder,
    write_phyletic_expression,
)
from veupathdb_mcp.catalog.phyletic_builder import READING_LIMIT
from veupathdb_mcp.catalog.phyletic_logic import Guard, atom, both, either
from veupathdb_mcp.catalog.site_cost import SiteCost
from veupathdb_mcp.tools.catalog_tools import build_phyletic_expression

PATTERN: TypeAdapter[PhyleticPattern] = TypeAdapter(PhyleticPattern)
T = TypeVar("T")
TREE = synthetic_tree()
GROUPS = synthetic_groups()


def _pattern(raw: JSONObject) -> PhyleticPattern:
    return PATTERN.validate_python(raw)


def _site(monkeypatch: pytest.MonkeyPatch) -> CountSite:
    return install(monkeypatch, site_counts(TREE, GROUPS), TREE)


async def _built(
    monkeypatch: pytest.MonkeyPatch, raw: JSONObject
) -> tuple[PhyleticExpressionResult, CountSite]:
    site = _site(monkeypatch)
    pattern = _pattern(raw)

    result = await write_phyletic_expression("orthomcl", pattern)

    parsed = PhyleticExpression.parse(result.expression)
    check_expression(parsed, TREE)
    truth = [holds(pattern, group, TREE) for group in GROUPS]
    assert [parsed.holds_for(group, TREE) for group in GROUPS] == truth
    assert result.groups == sum(truth)
    assert site.sent.count(result.expression) == 1
    assert site.sent[-1] == result.expression
    assert result.maximum_reads == len(site.sent) - 1
    assert result.codes == tuple(parsed.codes())
    described = parsed.describe(TREE)
    if len(described) <= READING_LIMIT and len(result.expression) <= READING_LIMIT:
        assert result.reading == described
    else:
        assert result.reading.endswith(f"{len(result.expression)} characters")
        assert len(result.reading) <= READING_LIMIT
    return result, site


def _count(of: JSONObject, measure: str, condition: str, value: float) -> JSONObject:
    return {
        "kind": "count",
        "of": of,
        "measure": measure,
        "condition": condition,
        "value": value,
    }


def _codes(*codes: str) -> JSONObject:
    return {"kind": "codes", "codes": list(codes)}


@pytest.mark.parametrize(
    ("raw", "expression"),
    [
        (_count(_codes("XA"), "genomes", "at_least", 2), "XA>=2T"),
        (_count(_codes("xaa", "yaa"), "proteins", "exactly", 3), "xaa+yaa=3"),
        (
            {
                "kind": "count",
                "of": {"kind": "all_except", "codes": ["XA"]},
                "condition": "absent",
            },
            "YB+zza=0T",
        ),
        (
            _count(
                {"kind": "each_species_of", "codes": ["XA"]}, "share", "at_least", 50
            ),
            "xaa+xab>=1T AND xac>=1T AND xba>=1T",
        ),
        (
            _count(
                {"kind": "each_genome_of", "codes": ["XG"]}, "proteins", "at_least", 2
            ),
            "xaa>=2 AND xab>=2 AND xac>=2",
        ),
    ],
)
async def test_each_set_kind_writes_its_units_from_the_tree(
    monkeypatch: pytest.MonkeyPatch, raw: JSONObject, expression: str
) -> None:
    result, site = await _built(monkeypatch, raw)

    assert result.expression == expression
    assert site.sent == [expression]
    assert result.maximum_reads == 0


async def test_each_genome_with_a_bound_that_admits_absence_multiplies_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = await _built(
        monkeypatch,
        _count({"kind": "each_genome_of", "codes": ["YB"]}, "proteins", "at_most", 1),
    )

    assert len(result.expression.split(" OR ")) == 2**4
    assert "yaa=0 AND yab=0 AND yac=0 AND yba=0" in result.expression


@pytest.mark.parametrize("measure", ["genomes", "proteins"])
@pytest.mark.parametrize(
    "condition", ["at_least", "at_most", "exactly", "more_than", "fewer_than"]
)
@pytest.mark.parametrize("value", [1, 2, 3])
async def test_each_condition_selects_the_groups_it_states(
    monkeypatch: pytest.MonkeyPatch, measure: str, condition: str, value: int
) -> None:
    await _built(monkeypatch, _count(_codes("XA"), measure, condition, value))


async def test_absent_is_no_protein_in_any_genome_of_the_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = await _built(
        monkeypatch, {"kind": "count", "of": _codes("XG", "zza"), "condition": "absent"}
    )

    assert result.expression == "XG+zza=0T"


@pytest.mark.parametrize(
    ("codes", "condition", "share", "expression"),
    [
        (["XG"], "at_least", 50, "XG>=2T"),
        (["XG"], "more_than", 50, "XG>=2T"),
        (["XG"], "at_most", 50, "XG=0T OR XG=1T"),
        (["XG"], "fewer_than", 50, "XG=0T OR XG=1T"),
        (["XA"], "exactly", 50, "XA=2T"),
        (["XA"], "at_least", 90, "XA>=4T"),
        (["XA"], "at_least", 26, "XA>=2T"),
        (["XA"], "more_than", 25, "XA>=2T"),
        (["XA"], "at_most", 74, "XA=0T OR XA<=2T"),
        (["XA"], "fewer_than", 75, "XA=0T OR XA<=2T"),
    ],
)
async def test_a_share_is_a_genome_count_rounded_by_its_condition(
    monkeypatch: pytest.MonkeyPatch,
    codes: list[str],
    condition: str,
    share: float,
    expression: str,
) -> None:
    result, _ = await _built(
        monkeypatch, _count(_codes(*codes), "share", condition, share)
    )

    assert result.expression == expression


async def test_exactly_a_share_that_is_no_whole_genome_count_matches_no_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch)

    with pytest.raises(ValidationError, match="matches no group"):
        await write_phyletic_expression(
            "orthomcl", _pattern(_count(_codes("XG"), "share", "exactly", 50))
        )

    assert site.sent == []


async def test_a_share_is_counted_per_species(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = await _built(
        monkeypatch,
        _count({"kind": "each_species_of", "codes": ["YB"]}, "share", "at_least", 60),
    )

    assert result.expression == "yaa+yab+yac>=2T AND yba>=1T"


def _compare(
    reading: str, condition: str, factor: float, left: JSONObject, right: JSONObject
) -> JSONObject:
    return {
        "kind": "compare",
        "left": left,
        "right": right,
        "reading": reading,
        "condition": condition,
        "factor": factor,
    }


@pytest.mark.parametrize("reading", ["per_genome", "totals", "averages"])
@pytest.mark.parametrize(
    "condition", ["at_least", "at_most", "exactly", "more_than", "fewer_than"]
)
@pytest.mark.parametrize("factor", [1, 2, 1.5])
@pytest.mark.parametrize(
    ("left", "right"),
    [
        (_codes("xba"), _codes("zza")),
        (_codes("XG"), _codes("yaa", "yba")),
        (_codes("YB"), {"kind": "all_except", "codes": ["YB", "XG"]}),
    ],
)
async def test_a_comparison_is_bands_that_agree_with_its_reading(
    monkeypatch: pytest.MonkeyPatch,
    reading: str,
    condition: str,
    factor: float,
    left: JSONObject,
    right: JSONObject,
) -> None:
    result, site = await _built(
        monkeypatch, _compare(reading, condition, factor, left, right)
    )

    assert result.maximum_reads >= 1
    assert site.most_in_flight == 1


async def test_two_single_genomes_compare_as_a_ladder_over_the_read_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, site = await _built(
        monkeypatch, _compare("totals", "more_than", 1, _codes("xba"), _codes("zza"))
    )

    assert site.sent[:-1] == [
        "zza>=128",
        "zza>=64",
        "zza>=32",
        "zza>=16",
        "zza>=8",
        "zza>=4",
        "zza>=6",
        "zza>=5",
    ]
    assert result.expression == (
        "zza=0 AND xba>=1 OR zza=1 AND xba>=2 OR zza=2 AND xba>=3 "
        "OR zza=3 AND xba>=4 OR zza=4 AND xba>=5"
    )


async def test_an_average_scales_each_band_by_the_genome_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = await _built(
        monkeypatch,
        _compare("averages", "at_least", 1, _codes("xba"), _codes("yaa", "yba")),
    )

    assert result.expression.startswith("yaa+yba=0 OR yaa+yba=1 AND xba>=1 OR ")
    assert "yaa+yba=3 AND xba>=2 OR yaa+yba=4 AND xba>=2" in result.expression


async def test_a_read_maximum_is_read_once_for_two_comparisons_of_one_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    right = _codes("yaa", "yba")
    result, site = await _built(
        monkeypatch,
        {
            "kind": "any_of",
            "terms": [
                _compare("totals", "more_than", 2, _codes("xba"), right),
                _compare("averages", "fewer_than", 1, _codes("XG"), right),
            ],
        },
    )

    assert len(site.sent[:-1]) == len(set(site.sent[:-1])) == result.maximum_reads


NESTED: list[JSONObject] = [
    {
        "kind": "all_of",
        "terms": [
            {
                "kind": "any_of",
                "terms": [
                    _count(_codes("XG"), "genomes", "at_least", 2),
                    _count(_codes("yaa"), "proteins", "more_than", 2),
                ],
            },
            {
                "kind": "any_of",
                "terms": [
                    _count(_codes("YB"), "share", "at_most", 50),
                    {"kind": "count", "of": _codes("zza"), "condition": "absent"},
                ],
            },
        ],
    },
    {
        "kind": "none_of",
        "terms": [
            {
                "kind": "all_of",
                "terms": [
                    _count(_codes("XA"), "genomes", "at_least", 1),
                    _count(_codes("YB"), "proteins", "fewer_than", 3),
                ],
            },
            _count(_codes("zza"), "proteins", "exactly", 2),
        ],
    },
    {
        "kind": "all_of",
        "terms": [
            _count(_codes("XA"), "genomes", "at_least", 1),
            {
                "kind": "none_of",
                "terms": [
                    {
                        "kind": "any_of",
                        "terms": [
                            _compare(
                                "per_genome",
                                "more_than",
                                1,
                                _codes("xaa"),
                                _codes("yaa"),
                            ),
                            _count(
                                {"kind": "each_species_of", "codes": ["YB"]},
                                "genomes",
                                "at_least",
                                1,
                            ),
                        ],
                    }
                ],
            },
        ],
    },
    {
        "kind": "any_of",
        "terms": [
            {
                "kind": "all_of",
                "terms": [
                    _compare("averages", "more_than", 1, _codes("XG"), _codes("YB")),
                    {"kind": "count", "of": _codes("zza"), "condition": "absent"},
                ],
            },
            {
                "kind": "none_of",
                "terms": [
                    _count(
                        {"kind": "each_genome_of", "codes": ["XG"]},
                        "proteins",
                        "at_least",
                        1,
                    )
                ],
            },
        ],
    },
]


@pytest.mark.parametrize("raw", NESTED)
async def test_nesting_multiplies_out_to_what_the_nested_pattern_means(
    monkeypatch: pytest.MonkeyPatch, raw: JSONObject
) -> None:
    result, _ = await _built(monkeypatch, raw)

    assert "(" not in result.expression


@pytest.mark.parametrize(
    ("raw", "named"),
    [
        (_count(_codes("QQQ"), "genomes", "at_least", 1), "QQQ"),
        (
            {
                "kind": "count",
                "of": {"kind": "all_except", "codes": ["XA", "YB", "zza"]},
                "condition": "absent",
            },
            "no genome",
        ),
        (_count(_codes("XA"), "proteins", "at_least", 0), "every group"),
        (
            _count(
                {"kind": "each_species_of", "codes": ["YB"]}, "genomes", "at_least", 2
            ),
            "matches no group",
        ),
        (_count(_codes("XA"), "genomes", "more_than", 4), "matches no group"),
        (
            {
                "kind": "all_of",
                "terms": [
                    _count(_codes("XA"), "genomes", "at_least", 1),
                    {"kind": "count", "of": _codes("XA"), "condition": "absent"},
                ],
            },
            "matches no group",
        ),
        (
            {
                "kind": "all_of",
                "terms": [
                    _count(_codes("XA"), "proteins", "at_least", 2),
                    {"kind": "count", "of": _codes("XA"), "condition": "absent"},
                ],
            },
            "matches no group",
        ),
        (
            {
                "kind": "all_of",
                "terms": [
                    _compare("totals", "more_than", 1, _codes("xba"), _codes("zza")),
                    _count(_codes("QQQ"), "genomes", "at_least", 1),
                ],
            },
            "QQQ",
        ),
    ],
)
async def test_a_pattern_the_site_cannot_read_is_refused_before_any_report(
    monkeypatch: pytest.MonkeyPatch, raw: JSONObject, named: str
) -> None:
    site = _site(monkeypatch)

    with pytest.raises(ValidationError) as refused:
        await write_phyletic_expression("orthomcl", _pattern(raw))

    assert named in (refused.value.detail or "")
    assert site.sent == []


@pytest.mark.parametrize(
    "raw",
    [
        _count(_codes("XA"), "genomes", "at_least", 1.5),
        _count(_codes("XA"), "share", "at_least", 120),
        {"kind": "count", "of": _codes("XA"), "condition": "absent", "value": 1},
        {"kind": "count", "of": _codes("XA"), "condition": "at_least"},
        _compare("totals", "more_than", 0, _codes("xba"), _codes("zza")),
        {
            "kind": "compare",
            "left": {"kind": "each_genome_of", "codes": ["XA"]},
            "right": _codes("zza"),
            "reading": "totals",
            "condition": "more_than",
        },
        {"kind": "any_of", "terms": []},
    ],
)
def test_an_ill_formed_pattern_is_refused_by_its_model(raw: JSONObject) -> None:
    with pytest.raises(PydanticValidationError):
        _pattern(raw)


def _each_wide_genome_at_most_one() -> JSONObject:
    return _count({"kind": "each_genome_of", "codes": ["WD"]}, "proteins", "at_most", 1)


async def test_a_pattern_past_the_term_cap_is_refused_unsent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, lambda expression: 1, wide_tree(16))

    with pytest.raises(PhyleticExpressionTooLargeError) as refused:
        await write_phyletic_expression(
            "orthomcl", _pattern(_each_wide_genome_at_most_one())
        )

    characters = 2**16 * 139 + 4 * (2**16 - 1)
    assert refused.value.detail == (
        "The pattern expands past what one search can run. The pattern writes "
        f"{2**16} OR terms, {characters} characters, past the {MAX_EXPRESSION_TERMS} "
        "OR terms one search can run; the site's parser recurses once per operator, "
        "and no longer expression was measured safe. This is a limit of this "
        "library, not a failure of the site. Narrow the pattern: fewer genomes under "
        "a bound that admits absence, fewer any_of terms under all_of, or a compare "
        "over a side with smaller counts."
    )
    assert site.sent == []


async def test_a_long_pattern_within_the_cap_is_written_whole_and_read_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, lambda expression: 1, wide_tree(10))

    result = await write_phyletic_expression(
        "orthomcl", _pattern(_each_wide_genome_at_most_one())
    )

    characters = 2**10 * 85 + 4 * (2**10 - 1)
    assert len(result.expression) == characters <= CHARACTERS_WITHIN_READ_TIMEOUT
    assert result.reading == (
        "at most 1 proteins in each genome of WD; written as 1024 OR terms, "
        f"{characters} characters"
    )
    assert site.sent == [result.expression]


async def test_the_reading_stays_short_however_long_the_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, lambda expression: 1, wide_tree(10))
    repeated = {"kind": "any_of", "terms": [_each_wide_genome_at_most_one()] * 100}

    result = await write_phyletic_expression("orthomcl", _pattern(repeated))

    assert len(result.reading) == READING_LIMIT
    assert result.reading.startswith("any of (at most 1 proteins in each genome of WD;")
    assert " ...; written as 1024 OR terms" in result.reading


def _largest_right(top: int) -> Callable[[str], int]:
    def answer(expression: str) -> int:
        probe = re.fullmatch(r"wz>=(\d+)", expression)
        if probe is None:
            return 1
        return 1 if int(probe[1]) <= top else 0

    return answer


def _wide_comparison() -> PhyleticPattern:
    left = [f"w{letter}" for letter in "abcdefghijklmnopqrstuvwxy"]
    return _pattern(_compare("totals", "more_than", 1, _codes(*left), _codes("wz")))


async def test_a_comparison_past_the_cap_is_refused_before_its_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, _largest_right(30000), wide_tree(26))

    with pytest.raises(PhyleticExpressionTooLargeError) as refused:
        await write_phyletic_expression("orthomcl", _wide_comparison())

    detail = refused.value.detail or ""
    assert detail.startswith(
        "The pattern expands past what one search can run. Multiplied out, the "
        "pattern reaches at least "
    )
    assert all(sent.startswith("wz>=") for sent in site.sent)


async def test_a_comparison_within_the_cap_sends_its_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, _largest_right(1200), wide_tree(26))

    result = await write_phyletic_expression("orthomcl", _wide_comparison())

    assert result.expression.count(" OR ") == 1200
    assert site.sent[-1] == result.expression


def test_the_predicted_time_is_a_second_guard() -> None:
    slow = SiteCost(fixed=4.0, per_character=0.003, longest=10**9)
    guard = Guard(TREE, slow, probes=2)

    with pytest.raises(PhyleticExpressionTooSlowError) as refused:
        guard.admit(140_000, 100)

    assert refused.value.detail == (
        "The pattern writes 100 OR terms, 140000 characters: the site was measured "
        "to count 3000 ms per 1,000 characters plus 4.0 s, so it needs about 425 s, "
        "past the 300 s call budget. Narrow the pattern: fewer genomes under a bound "
        "that admits absence, fewer any_of terms under all_of, or a compare over a "
        "side with smaller counts."
    )


def test_a_product_is_admitted_on_its_merged_size() -> None:
    guard = Guard(TREE, SiteCost(fixed=0.0, per_character=0.5, longest=600), 0)
    exact = either(
        [atom(frozenset({"xaa"}), (k, k), taxa=False) for k in range(1, 41)], guard
    )

    merged = both([exact, exact], guard)

    assert len(merged) == 40


async def test_the_expansion_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)
    moved: list[str] = []
    to_thread = asyncio.to_thread

    async def recorded(function: Callable[..., T], /, *args: object) -> T:
        moved.append(function.__name__)
        return await to_thread(function, *args)

    monkeypatch.setattr(phyletic_builder.asyncio, "to_thread", recorded)

    await write_phyletic_expression(
        "orthomcl", _pattern(_count(_codes("XA"), "genomes", "at_least", 2))
    )

    assert moved == ["probed", "written"]


async def test_every_genome_is_a_set(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = await _built(
        monkeypatch, _count(_codes("ALL"), "share", "at_least", 50)
    )

    assert result.expression == "XA+YB+zza>=5T"


async def test_one_right_genome_compares_per_genome_in_exact_bands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    per_genome, _ = await _built(
        monkeypatch,
        _compare("per_genome", "more_than", 1, _codes("xba"), _codes("zza")),
    )
    totals, _ = await _built(
        monkeypatch, _compare("totals", "more_than", 1, _codes("xba"), _codes("zza"))
    )

    assert per_genome.expression == totals.expression


def test_a_count_offers_no_measure_or_value_it_would_refuse() -> None:
    schema = CountTerm.model_json_schema(by_alias=True)["properties"]

    assert (schema["measure"]["default"], schema["value"]["default"]) == (None, None)


async def test_the_sites_refusal_reaches_the_caller_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = "The phyletic_expression could not be parsed at character 4000."

    def refuse(expression: str) -> int:
        raise WDKError(detail=refusal, status=422)

    install(monkeypatch, refuse, TREE)

    with pytest.raises(ToolError) as served:
        await build_phyletic_expression(
            "orthomcl", _pattern(_count(_codes("XA"), "genomes", "at_least", 2))
        )

    assert str(served.value) == refusal


async def test_the_served_tool_answers_the_built_expression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch)

    result = await build_phyletic_expression(
        "orthomcl", _pattern(_count(_codes("XA"), "genomes", "at_least", 2))
    )

    assert (result.site_id, result.expression, result.codes) == (
        "orthomcl",
        "XA>=2T",
        ("XA",),
    )
    assert result.reading == (
        "at least 2 genomes of Clade X (4 genomes of 3 species; Xalpha one 2)"
    )


@pytest.mark.parametrize("kind", ["all_of", "any_of", "none_of"])
def test_a_combined_pattern_serializes_like_any_value(kind: str) -> None:
    pattern = TypeAdapter(PhyleticPattern).validate_python(
        {
            "kind": kind,
            "terms": [
                {
                    "kind": "count",
                    "of": {"kind": "codes", "codes": ["XA"]},
                    "condition": "absent",
                }
            ],
        }
    )

    assert to_jsonable_python(pattern)["kind"] == kind
