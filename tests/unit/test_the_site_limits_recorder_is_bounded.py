from scripts.record_phyletic_site_limits import (
    MAX_READS,
    Answered,
    Planned,
    measure,
    plan,
)
from tests._support.phyletic_truth import wide_tree

from veupathdb_mcp.catalog import MAX_EXPRESSION_TERMS, MAX_EXPRESSION_WORK


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _planned(count: int) -> list[Planned]:
    return [
        Planned(series="ladder", terms=n, expression=f"zza={n}") for n in range(count)
    ]


def test_the_plan_grows_by_terms_and_by_characters_within_the_read_bound() -> None:
    planned = plan(wide_tree(26), "wa", "wz")

    ladders = [step for step in planned if step.series == "ladder"]
    wides = [step for step in planned if step.series.startswith("wide")]
    assert len(planned) <= MAX_READS
    assert [step.terms for step in ladders] == sorted(step.terms for step in ladders)
    assert [step.expression.count(" OR ") + 1 for step in ladders] == [
        step.terms for step in ladders
    ]
    assert ladders[0].expression.startswith("wz=0 AND wa>=1 OR wz=1 AND wa>=2")
    assert [step.series for step in wides] == ["wide-8", "wide-25"]
    assert len(wides[-1].expression) > len(wides[0].expression)


def test_the_plan_sends_nothing_past_the_expression_caps() -> None:
    planned = plan(wide_tree(26), "wa", "wz")

    assert max(step.terms for step in planned) == MAX_EXPRESSION_TERMS
    assert all(
        step.terms * len(step.expression) <= MAX_EXPRESSION_WORK for step in planned
    )


async def test_a_refusal_ends_the_run_at_the_read_it_answered() -> None:
    clock = _Clock()
    sent: list[str] = []

    async def send(expression: str, remaining: float) -> Answered:
        sent.append(expression)
        return Answered(status=500 if len(sent) == 3 else 200, total=1)

    measured, stopped = await measure(_planned(10), send, clock)

    assert (len(sent), len(measured), stopped) == (3, 3, "status 500")
    assert measured[-1].status == 500


async def test_the_run_ends_when_its_three_hundred_seconds_are_spent() -> None:
    clock = _Clock()
    budgets: list[float] = []

    async def send(expression: str, remaining: float) -> Answered:
        budgets.append(remaining)
        clock.now += 100.0
        return Answered(status=200, total=1)

    measured, stopped = await measure(_planned(10), send, clock)

    assert (budgets, stopped) == ([300.0, 200.0, 100.0], "budget")
    assert [step.seconds for step in measured] == [100.0, 100.0, 100.0]


async def test_no_run_sends_more_than_thirty_reads() -> None:
    sent: list[str] = []

    async def send(expression: str, remaining: float) -> Answered:
        sent.append(expression)
        return Answered(status=200, total=1)

    measured, stopped = await measure(_planned(45), send, _Clock())

    assert (len(sent), len(measured), stopped) == (MAX_READS, 30, "plan")
