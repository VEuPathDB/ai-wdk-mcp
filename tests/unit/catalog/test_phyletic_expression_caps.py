import re
from collections.abc import Callable

import pytest
from pydantic import TypeAdapter
from tests._support.group_count_site import install
from tests._support.phyletic_truth import synthetic_tree, wide_tree
from veupathdb import JSONObject
from veupathdb.errors import ValidationError
from veupathdb.wdk.site_router import RoutingConfig

from veupathdb_mcp.catalog import (
    CHARACTERS_WITHIN_READ_TIMEOUT,
    MAX_EXPRESSION_TERMS,
    MAX_EXPRESSION_WORK,
    PhyleticExpressionTooLargeError,
    PhyleticPattern,
    write_phyletic_expression,
)
from veupathdb_mcp.catalog.phyletic_logic import Guard
from veupathdb_mcp.catalog.site_cost import (
    READ_TIMEOUT_SECONDS,
    measured_rows,
    site_cost,
)

PATTERN: TypeAdapter[PhyleticPattern] = TypeAdapter(PhyleticPattern)
WIDE = wide_tree(26)


def _exactly(codes: list[str], value: int) -> JSONObject:
    return {
        "kind": "count",
        "of": {"kind": "codes", "codes": codes},
        "measure": "proteins",
        "condition": "exactly",
        "value": value,
    }


def _grid(left: list[str], lefts: int, right: list[str], rights: int) -> JSONObject:
    return {
        "kind": "all_of",
        "terms": [
            {
                "kind": "any_of",
                "terms": [_exactly(left, k) for k in range(1, lefts + 1)],
            },
            {
                "kind": "any_of",
                "terms": [_exactly(right, k) for k in range(1, rights + 1)],
            },
        ],
    }


async def _refused(
    monkeypatch: pytest.MonkeyPatch, raw: JSONObject
) -> tuple[PhyleticExpressionTooLargeError, list[str]]:
    site = install(monkeypatch, lambda expression: 1, WIDE)

    with pytest.raises(PhyleticExpressionTooLargeError) as refused:
        await write_phyletic_expression("orthomcl", PATTERN.validate_python(raw))

    return refused.value, site.sent


def _guard() -> Guard:
    return Guard(WIDE, site_cost(), 0)


async def test_an_expression_of_one_term_past_the_cap_is_refused_unsent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error, sent = await _refused(monkeypatch, _grid(["wa"], 69, ["wb"], 29))

    assert (error.limit, error.terms, error.cap) == (
        "terms",
        MAX_EXPRESSION_TERMS + 1,
        MAX_EXPRESSION_TERMS,
    )
    assert isinstance(error, ValidationError)
    assert sent == []
    assert (error.detail or "").startswith(
        "The pattern expands past what one search can run. Multiplied out, the "
        f"pattern reaches at least {MAX_EXPRESSION_TERMS + 1} OR terms"
    )
    assert f"past the {MAX_EXPRESSION_TERMS} OR terms" in (error.detail or "")
    assert "a limit of this library, not a failure of the site" in (error.detail or "")


async def test_an_expression_of_as_many_terms_as_the_cap_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, lambda expression: 1, WIDE)

    result = await write_phyletic_expression(
        "orthomcl", PATTERN.validate_python(_grid(["wa"], 40, ["wb"], 50))
    )

    assert result.expression.count(" OR ") + 1 == MAX_EXPRESSION_TERMS
    assert site.sent == [result.expression]


def test_an_expression_one_character_past_the_cap_is_refused() -> None:
    with pytest.raises(PhyleticExpressionTooLargeError) as refused:
        _guard().admit(CHARACTERS_WITHIN_READ_TIMEOUT + 1, 1)

    error = refused.value
    assert (error.limit, error.characters, error.cap) == (
        "characters",
        CHARACTERS_WITHIN_READ_TIMEOUT + 1,
        CHARACTERS_WITHIN_READ_TIMEOUT,
    )
    assert error.detail == (
        "The pattern expands past what one search can run. The pattern writes 1 OR "
        f"terms, {CHARACTERS_WITHIN_READ_TIMEOUT + 1} characters, past the "
        f"{CHARACTERS_WITHIN_READ_TIMEOUT} characters one search counts within the "
        f"{READ_TIMEOUT_SECONDS} s read timeout. This is a limit of this library, not "
        "a failure of the site. Narrow the pattern: fewer genomes under a bound that "
        "admits absence, fewer any_of terms under all_of, or a compare over a side "
        "with smaller counts."
    )


def test_an_expression_as_long_as_the_cap_is_admitted() -> None:
    _guard().admit(CHARACTERS_WITHIN_READ_TIMEOUT, 1)


def test_the_character_cap_is_counted_within_the_read_timeout() -> None:
    answered = [characters for characters, seconds in measured_rows() if seconds < 30]

    assert RoutingConfig().component_timeout == READ_TIMEOUT_SECONDS
    assert site_cost().seconds(CHARACTERS_WITHIN_READ_TIMEOUT, 0) < READ_TIMEOUT_SECONDS
    assert CHARACTERS_WITHIN_READ_TIMEOUT < max(answered) == 165028


def test_an_expression_one_unit_of_work_past_the_cap_is_refused() -> None:
    with pytest.raises(PhyleticExpressionTooLargeError) as refused:
        _guard().admit(80_001, MAX_EXPRESSION_TERMS)

    error = refused.value
    assert (error.limit, error.work, error.cap) == (
        "work",
        80_001 * MAX_EXPRESSION_TERMS,
        MAX_EXPRESSION_WORK,
    )
    assert (
        f"its OR terms times its characters, {80_001 * MAX_EXPRESSION_TERMS}, pass the "
        f"{MAX_EXPRESSION_WORK} one search can parse"
    ) in (error.detail or "")


def test_an_expression_of_as_much_work_as_the_cap_is_admitted() -> None:
    _guard().admit(80_000, MAX_EXPRESSION_TERMS)


def test_the_work_cap_is_half_the_largest_product_measured_safe() -> None:
    assert MAX_EXPRESSION_WORK <= 250 * 1_298_778 // 2


async def test_the_most_terms_over_too_many_characters_are_refused_unsent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seven = [f"w{letter}" for letter in "abcdefg"]
    others = [f"w{letter}" for letter in "hijklmn"]

    error, sent = await _refused(monkeypatch, _grid(seven, 40, others, 50))

    assert error.limit == "work"
    assert error.terms <= MAX_EXPRESSION_TERMS
    assert error.characters <= CHARACTERS_WITHIN_READ_TIMEOUT
    assert error.work > MAX_EXPRESSION_WORK
    assert sent == []


def _largest_per_genome(top: int) -> Callable[[str], int]:
    def answer(expression: str) -> int:
        probe = re.fullmatch(r"y[a-z]{2}>=(\d+)(?: OR y[a-z]{2}>=\1)*", expression)
        if probe is None:
            return 1
        return 1 if int(probe[1]) <= top else 0

    return answer


async def test_each_genome_of_a_clade_compared_pairwise_is_refused_before_its_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = install(monkeypatch, _largest_per_genome(200), synthetic_tree())
    pattern = {
        "kind": "compare",
        "left": {"kind": "codes", "codes": ["XA"]},
        "right": {"kind": "codes", "codes": ["YB"]},
        "reading": "per_genome",
        "condition": "more_than",
    }

    with pytest.raises(PhyleticExpressionTooLargeError) as refused:
        await write_phyletic_expression("orthomcl", PATTERN.validate_python(pattern))

    assert refused.value.limit == "terms"
    assert refused.value.terms > MAX_EXPRESSION_TERMS
    assert site.sent
    assert all(sent.startswith("yaa>=") for sent in site.sent)
