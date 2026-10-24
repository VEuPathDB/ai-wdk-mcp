from collections import Counter
from collections.abc import Callable

import pytest
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter
from tests._support import group_count_site
from tests._support.group_cloud_site import (
    CloudSite,
    Codes,
    cloud_body,
    cloud_counts,
    recorded,
    recorded_tree,
    serve_clouds,
    set_codes,
    total_of,
)
from veupathdb import JSONObject
from veupathdb.domain.parameters import PhyleticExpression, PhyleticTree, TaxonEntry

from veupathdb_mcp.catalog import (
    AbsentGroupsCompareError,
    CompareTerm,
    PhyleticExpressionTooLargeError,
    PhyleticExpressionTooSlowError,
    PhyleticPattern,
    phyletic_logic,
    write_phyletic_expression,
)
from veupathdb_mcp.catalog.phyletic_builder import Probed
from veupathdb_mcp.catalog.phyletic_logic import CALL_SECONDS, Guard, clock, cover
from veupathdb_mcp.catalog.site_cost import site_cost
from veupathdb_mcp.testing import ORTHOMCL_COUNTS
from veupathdb_mcp.tools.catalog_tools import build_phyletic_expression
from veupathdb_mcp.wdk import (
    MAX_COMPARISON_REQUESTS,
    ComparisonOutOfTimeError,
    ComparisonRequestsError,
    GenomePastCloudCapError,
    NestedCompareTooLargeError,
    PerGenomeNeedsTaskError,
    answer_phyletic_pattern,
    compute_comparison,
    phyletic_counts,
)

TREE = recorded_tree()
CODES = set_codes()
TOX = frozenset(CODES.tox)
PLAS = frozenset(CODES.plas)
TGON = frozenset({"tgon"})
PFAL = frozenset({"pfal"})
PLAS_CLOUD = cloud_counts("r04_plas_groupcloud")
TGON_CLOUD = cloud_counts("r02_tgon_groupcloud")
PFAL_CLOUD = cloud_counts("r02_pfal_groupcloud")
LONE = {"tgon>=1T": len(TGON_CLOUD), "pfal>=1T": len(PFAL_CLOUD)}
EVERY_LONE = {f"{code}>=1T" for code in TOX | PLAS | PFAL}


def _compare(left: Codes, right: Codes, reading: str, **more: object) -> JSONObject:
    return {
        "kind": "compare",
        "left": {"kind": "codes", "codes": sorted(left)},
        "right": {"kind": "codes", "codes": sorted(right)},
        "reading": reading,
        "condition": "more_than",
        **more,
    }


def _term(raw: JSONObject) -> CompareTerm:
    return CompareTerm.model_validate(raw)


def _ordered(genomes: Codes) -> tuple[str, ...]:
    return tuple(node.code for node in TREE.nodes() if node.code in genomes)


def _genus_groups(expression: str) -> int:
    plas = cover(TREE, PLAS)
    counted = {
        f"{cover(TREE, TOX)}>=1T": total_of("r01a_tox_ge1"),
        f"{plas}>=1T": total_of("r01b_plas_ge1"),
    }
    if expression in counted:
        return counted[expression]
    least = int(expression.removeprefix(f"{plas}>="))
    return sum(count >= least for count in PLAS_CLOUD.values())


def _genus_site(monkeypatch: pytest.MonkeyPatch) -> CloudSite:
    clouds: dict[Codes, JsonValue] = {
        TOX: recorded("r03_tox_groupcloud"),
        PLAS: recorded("r04_plas_groupcloud"),
    }
    records = {
        TOX: cloud_counts("r03_tox_abbrevcloud").total(),
        PLAS: cloud_counts("r04_plas_abbrevcloud").total(),
    }
    return serve_clouds(monkeypatch, CloudSite(clouds, records, _genus_groups), TREE)


def _single_site(
    monkeypatch: pytest.MonkeyPatch, groups: Callable[[str], int]
) -> CloudSite:
    clouds: dict[Codes, JsonValue] = {
        TGON: recorded("r02_tgon_groupcloud"),
        PFAL: recorded("r02_pfal_groupcloud"),
    }
    records = {TGON: total_of("r02_tgon_std"), PFAL: total_of("r02_pfal_std")}

    def answered(expression: str) -> int:
        return LONE[expression] if expression in LONE else groups(expression)

    return serve_clouds(monkeypatch, CloudSite(clouds, records, answered), TREE)


class _Report(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    expression: str
    total: int


class _Ladder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    reports: tuple[_Report, ...]


def _parts(genomes: Codes) -> list[tuple[str, ...]]:
    ordered = _ordered(genomes)
    if len(ordered) == 1:
        return []
    middle = len(ordered) // 2
    first, second = frozenset(ordered[:middle]), frozenset(ordered[middle:])
    return [ordered, *_parts(first), *_parts(second)]


def _never(expression: str) -> int:
    raise AssertionError(expression)


async def test_a_genus_mean_past_the_caps_is_computed_from_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _genus_site(monkeypatch)
    pattern = TypeAdapter(PhyleticPattern).validate_python(
        _compare(TOX, PLAS, "averages")
    )

    result = await build_phyletic_expression("orthomcl", pattern)

    assert result.route == "computed"
    assert (result.groups, result.both_held, result.left_only) == (7364, 1884, 5480)
    assert (result.right_only, result.ties, result.residual_groups) == (0, 371, 1969)
    left, right = result.sets
    assert (left.genomes, left.groups, left.proteins) == (15, 8014, 140798)
    assert (right.genomes, right.groups, right.proteins) == (61, 9396, 333932)
    assert left.species[0].model_dump() == {
        "species": "Toxoplasma gondii",
        "genomes": 15,
    }
    assert right.species[0].model_dump() == {
        "species": "Plasmodium falciparum",
        "genomes": 20,
    }
    assert sum(one.genomes for one in right.species) == 61
    assert (result.probe_requests, result.compute_requests) == (17, 6)
    assert site.kinds()[:17] == ["groups"] * 17
    assert site.kinds()[17:] == [
        "groups",
        "groups",
        "cloud",
        "records",
        "cloud",
        "records",
    ]
    assert site.most_in_flight == 1


async def test_the_genus_mean_passes_the_expression_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _genus_site(monkeypatch)
    pattern = TypeAdapter(PhyleticPattern).validate_python(
        _compare(TOX, PLAS, "averages")
    )

    with pytest.raises(PhyleticExpressionTooLargeError):
        await write_phyletic_expression("orthomcl", pattern)


async def test_a_genus_mean_at_twice_the_right_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _genus_site(monkeypatch)

    result = await compute_comparison(
        "orthomcl", _term(_compare(TOX, PLAS, "averages", factor=2))
    )

    assert (result.both_held, result.left_only) == (317, 5480)


@pytest.mark.parametrize("condition", ["at_least", "at_most", "exactly"])
async def test_a_compare_that_selects_groups_neither_set_holds_reads_nothing(
    monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    site = _single_site(monkeypatch, _never)

    with pytest.raises(AbsentGroupsCompareError):
        await compute_comparison(
            "orthomcl", _term(_compare(TGON, PFAL, "totals", condition=condition))
        )

    assert site.sent == []


async def test_one_genome_each_per_genome_matches_the_expression_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _single_site(monkeypatch, _never)

    result = await compute_comparison(
        "orthomcl", _term(_compare(TGON, PFAL, "per_genome"))
    )

    assert (result.groups, result.both_held, result.left_only) == (3896, 362, 3534)
    assert (result.probe_requests, result.compute_requests) == (0, 6)
    assert site.kinds() == ["groups", "groups", "cloud", "records", "cloud", "records"]
    assert all(0 < (budget or 0) <= CALL_SECONDS for budget in site.budgets)
    assert len(site.budgets) == 2


async def test_one_genome_past_the_word_cap_is_refused_before_a_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = serve_clouds(
        monkeypatch,
        CloudSite({}, {}, lambda expression: 10_001 if expression == "tgon>=1T" else 1),
        TREE,
    )

    with pytest.raises(GenomePastCloudCapError) as refused:
        await compute_comparison("orthomcl", _term(_compare(TGON, PFAL, "totals")))

    detail = refused.value.detail or ""
    assert (refused.value.genome, refused.value.groups) == ("tgon", 10_001)
    assert "tgon alone holds 10001 groups" in detail
    assert "fewer genomes" not in detail
    assert site.kinds() == ["groups"]


async def test_a_comparison_past_the_call_budget_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _single_site(monkeypatch, _never)

    with pytest.raises(ComparisonOutOfTimeError):
        await compute_comparison(
            "orthomcl",
            _term(_compare(TGON, PFAL, "totals")),
            started=clock() - CALL_SECONDS - 1,
        )

    assert site.sent == []


async def test_an_under_cap_compare_still_writes_an_expression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ladder = _Ladder.model_validate_json(
        (ORTHOMCL_COUNTS / "orthomcl_protein_count_ladder.json").read_text()
    )
    totals = {
        report.expression.replace("(", "").replace(")", ""): report.total
        for report in ladder.reports
    }
    group_count_site.install(monkeypatch, totals.__getitem__, TREE)
    pattern = TypeAdapter(PhyleticPattern).validate_python(
        _compare(TGON, PFAL, "totals")
    )

    result = await answer_phyletic_pattern("orthomcl", pattern)

    assert (result.route, result.groups) == ("expression", 3896)


PAIR = PhyleticTree.from_taxa(
    [
        TaxonEntry(id=code, parent_id=None, code=code, label=code, clade=False)
        for code in ("tgon", "pfal")
    ]
)


def _selected(expression: str) -> set[str]:
    read = PhyleticExpression.parse(expression)
    pairs = {
        group: (TGON_CLOUD[group], PFAL_CLOUD[group])
        for group in set(TGON_CLOUD) | set(PFAL_CLOUD)
    }
    held = {
        pair: read.holds_for({"tgon": pair[0], "pfal": pair[1]}, PAIR)
        for pair in set(pairs.values())
    }
    return {group for group, pair in pairs.items() if held[pair]}


async def test_the_computed_ids_are_the_recorded_ladders_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ladder = _Ladder.model_validate_json(
        (ORTHOMCL_COUNTS / "orthomcl_protein_count_ladder.json").read_text()
    )
    totals = {
        report.expression.replace("(", "").replace(")", ""): report.total
        for report in ladder.reports
    }
    group_count_site.install(monkeypatch, totals.__getitem__, TREE)
    pattern = TypeAdapter(PhyleticPattern).validate_python(
        _compare(TGON, PFAL, "totals")
    )
    written = await write_phyletic_expression("orthomcl", pattern)
    _single_site(monkeypatch, _never)

    computed = await compute_comparison(
        "orthomcl", _term(_compare(TGON, PFAL, "totals"))
    )

    assert set(computed.group_ids) == _selected(written.expression)
    assert computed.groups == written.groups == 3896


def _pfal_probes(expression: str) -> int:
    if expression.startswith("pfal>="):
        least = int(expression.removeprefix("pfal>="))
        return sum(count >= least for count in PFAL_CLOUD.values())
    return len(_selected(expression))


async def test_a_fewer_than_compare_takes_the_right_only_groups_as_its_expression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_count_site.install(monkeypatch, _pfal_probes, TREE)
    raw = _compare(TGON, PFAL, "totals", condition="fewer_than")
    written = await write_phyletic_expression(
        "orthomcl", TypeAdapter(PhyleticPattern).validate_python(raw)
    )
    _single_site(monkeypatch, _never)

    computed = await compute_comparison("orthomcl", _term(raw))

    assert set(computed.group_ids) == _selected(written.expression)
    assert computed.right_only == len(set(PFAL_CLOUD) - set(TGON_CLOUD))
    assert computed.left_only == 0


async def test_a_set_past_the_word_cap_is_read_in_slices_and_summed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordered = _ordered(TOX)
    first, second = ordered[: len(ordered) // 2], ordered[len(ordered) // 2 :]
    whole = cloud_counts("r03_tox_groupcloud")
    spanning = next(group for group, count in whole.items() if count > 1)
    halves: tuple[Counter[str], Counter[str]] = (Counter(), Counter())
    for index, (group, count) in enumerate(whole.items()):
        if group == spanning:
            halves[0][group], halves[1][group] = 1, count - 1
        else:
            halves[index % 2][group] = count
    full = f"{cover(TREE, TOX)}>=1T"
    site = serve_clouds(
        monkeypatch,
        CloudSite(
            {
                frozenset(first): cloud_body(halves[0]),
                frozenset(second): cloud_body(halves[1]),
                PFAL: recorded("r02_pfal_groupcloud"),
            },
            {
                frozenset(first): halves[0].total(),
                frozenset(second): halves[1].total(),
                PFAL: total_of("r02_pfal_std"),
            },
            lambda expression: 10_001 if expression == full else 5_000,
        ),
        TREE,
    )

    result = await compute_comparison("orthomcl", _term(_compare(TOX, PFAL, "totals")))

    assert halves[0][spanning] + halves[1][spanning] == whole[spanning]
    left = result.sets[0]
    assert (left.groups, left.proteins) == (len(whole), whole.total())
    assert site.kinds() == ["groups"] * 4 + ["cloud", "records"] * 3
    assert (result.probe_requests, result.compute_requests) == (0, 10)


async def test_a_comparison_past_the_request_ceiling_is_refused_before_a_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = serve_clouds(
        monkeypatch,
        CloudSite(
            {}, {}, lambda expression: 5_000 if expression in EVERY_LONE else 10_001
        ),
        TREE,
    )

    with pytest.raises(ComparisonRequestsError) as refused:
        await compute_comparison("orthomcl", _term(_compare(TOX, PLAS, "averages")))

    assert "cloud" not in site.kinds()
    assert len(site.sent) == MAX_COMPARISON_REQUESTS
    assert refused.value.narrower
    assert "Compare narrower sets" in (refused.value.detail or "")


async def test_a_wide_per_genome_compare_needs_a_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = serve_clouds(monkeypatch, CloudSite({}, {}, _never), TREE)

    with pytest.raises(PerGenomeNeedsTaskError) as refused:
        await compute_comparison("orthomcl", _term(_compare(TOX, PLAS, "per_genome")))

    assert (refused.value.genomes, refused.value.needed) == (76, 228)
    assert site.sent == []


def _probed(reads: int, raw: JSONObject) -> Probed:
    guard = Guard(TREE, site_cost(), 0)
    pattern = TypeAdapter(PhyleticPattern).validate_python(raw)
    return Probed(guard, tuple(pattern.probes(guard)), {}, reads)


async def test_an_expression_too_slow_to_count_is_computed_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _single_site(monkeypatch, _never)
    raw = _compare(TGON, PFAL, "per_genome")
    too_slow = PhyleticExpressionTooSlowError(detail="past the call budget")

    async def probe(site_id: str, pattern: PhyleticPattern) -> Probed:
        del site_id, pattern
        return _probed(5, raw)

    async def slow(site_id: str, pattern: PhyleticPattern, found: Probed) -> None:
        del site_id, pattern, found
        raise too_slow

    monkeypatch.setattr(phyletic_counts, "probe_pattern", probe)
    monkeypatch.setattr(phyletic_counts, "expression_of", slow)

    result = await answer_phyletic_pattern(
        "orthomcl", TypeAdapter(PhyleticPattern).validate_python(raw)
    )

    assert (result.route, result.groups) == ("computed", 3896)
    assert (result.probe_requests, result.compute_requests) == (5, 6)


async def test_a_nested_compare_past_the_caps_is_refused_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _single_site(monkeypatch, _never)
    raw: JSONObject = {"kind": "all_of", "terms": [_compare(TGON, PFAL, "averages")]}
    too_large = PhyleticExpressionTooLargeError("terms", 2001, 9000, partial=False)

    async def probe(site_id: str, pattern: PhyleticPattern) -> Probed:
        del site_id, pattern
        return _probed(3, raw)

    async def large(site_id: str, pattern: PhyleticPattern, found: Probed) -> None:
        del site_id, pattern, found
        raise too_large

    monkeypatch.setattr(phyletic_counts, "probe_pattern", probe)
    monkeypatch.setattr(phyletic_counts, "expression_of", large)

    with pytest.raises(NestedCompareTooLargeError) as refused:
        await answer_phyletic_pattern(
            "orthomcl", TypeAdapter(PhyleticPattern).validate_python(raw)
        )

    detail = refused.value.detail or ""
    assert detail.startswith(too_large.detail or "")
    assert "sits inside all_of, any_of or none_of" in detail
    assert site.sent == []


async def test_a_pattern_too_large_without_its_compare_keeps_its_own_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _single_site(monkeypatch, _never)
    raw: JSONObject = {"kind": "all_of", "terms": [_compare(TGON, PFAL, "averages")]}
    too_large = PhyleticExpressionTooLargeError("terms", 2001, 9000, partial=False)

    async def probe(site_id: str, pattern: PhyleticPattern) -> Probed:
        del site_id, pattern
        return _probed(3, raw)

    async def large(site_id: str, pattern: PhyleticPattern, found: Probed) -> None:
        del site_id, pattern, found
        raise too_large

    monkeypatch.setattr(phyletic_counts, "probe_pattern", probe)
    monkeypatch.setattr(phyletic_counts, "expression_of", large)
    monkeypatch.setattr(phyletic_logic, "MAX_EXPRESSION_WORK", 1)

    with pytest.raises(PhyleticExpressionTooLargeError) as refused:
        await answer_phyletic_pattern(
            "orthomcl", TypeAdapter(PhyleticPattern).validate_python(raw)
        )

    assert refused.value is too_large


async def test_a_compare_whose_least_expression_passes_a_cap_reads_no_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _genus_site(monkeypatch)
    least = len(f"{cover(TREE, PLAS)}=0 AND {cover(TREE, TOX)}>=1")
    monkeypatch.setattr(phyletic_logic, "MAX_EXPRESSION_WORK", least - 1)
    pattern = TypeAdapter(PhyleticPattern).validate_python(
        _compare(TOX, PLAS, "averages")
    )

    result = await answer_phyletic_pattern("orthomcl", pattern)

    assert result.route == "computed"
    assert (result.probe_requests, result.compute_requests) == (0, 6)
    assert site.kinds() == ["groups", "groups", "cloud", "records", "cloud", "records"]


async def test_counts_that_fit_but_slices_that_do_not_are_refused_before_a_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sizes = {f"{cover(TREE, frozenset(part))}>=1T": len(part) for part in _parts(TOX)}
    sizes.update(dict.fromkeys(EVERY_LONE, 1))
    site = serve_clouds(
        monkeypatch,
        CloudSite({}, {}, lambda expression: 4_000 * sizes[expression]),
        TREE,
    )

    with pytest.raises(ComparisonRequestsError) as refused:
        await compute_comparison("orthomcl", _term(_compare(TOX, PFAL, "totals")))

    assert site.kinds() == ["groups"] * 16
    assert sorted(len(part) for part in refused.value.narrower) == [1, 1] + [2] * 7
    assert refused.value.needed == 16 + 2 * 9
