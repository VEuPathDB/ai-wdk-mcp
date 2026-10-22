import pytest
from scripts.record_orthomcl_every_species import (
    CRYPTOSPORIDIUM,
    REPORT_BUDGET,
    SEARCH,
    SITE,
    CountReport,
    CountTape,
)
from veupathdb import JSONObject
from veupathdb.wdk import WDKAnswer, WDKSearchConfig


class Inner:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        self.sent.append(search_config.parameters["phyletic_expression"])
        return WDKAnswer.model_validate(
            {"meta": {"totalCount": 7, "responseCount": 0}, "records": []}
        )


def config(expression: str) -> WDKSearchConfig:
    return WDKSearchConfig(parameters={"phyletic_expression": expression})


def test_the_recording_counts_cryptosporidium_once_on_orthomcl() -> None:
    assert (SITE, SEARCH, REPORT_BUDGET) == ("orthomcl", "GroupsByPhyleticPattern", 1)
    assert len(CRYPTOSPORIDIUM) == 18


async def test_a_count_report_is_kept_with_its_total() -> None:
    inner = Inner()
    tape = CountTape(inner, 1)

    await tape.run_search_report("group", SEARCH, config("a>=1T AND b>=1T"))

    assert tape.reports == [CountReport(expression="a>=1T AND b>=1T", total=7)]


async def test_a_report_past_the_budget_is_refused_unsent() -> None:
    inner = Inner()
    tape = CountTape(inner, 1)
    await tape.run_search_report("group", SEARCH, config("a>=1T"))

    with pytest.raises(RuntimeError, match="allows 1 GroupsByPhyleticPattern"):
        await tape.run_search_report("group", SEARCH, config("b>=1T"))

    assert inner.sent == ["a>=1T"]
