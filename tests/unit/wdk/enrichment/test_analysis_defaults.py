"""An analysis form supplies defaults that analysis creation will not apply.

Creation validates with no fill, so every value the form offered must be sent
back. Running with no parameters is a rejection, not a degraded run.
"""

from __future__ import annotations

import pytest
from veupathdb.errors import ExternalServiceError
from veupathdb.wdk.client import VEuPathDBClient
from veupathdb.wdk.strategy_api.api import StrategyAPI
from veupathdb.wdk.wdk_parameters import (
    WDKNumberParam,
    WDKParameter,
    WDKStringParam,
)

from veupathdb_mcp.wdk.enrichment.params import extract_default_params
from veupathdb_mcp.wdk.enrichment.service import EnrichmentService


def _form() -> list[WDKParameter]:
    return [
        WDKStringParam(
            name="organism",
            display_name="Organism",
            initial_display_value="Plasmodium falciparum 3D7",
        ),
        WDKNumberParam(
            name="pValueCutoff",
            display_name="P-value cutoff",
            initial_display_value="0.05",
        ),
    ]


class TestTheFormDefaultsAreCarriedBack:
    def test_every_offered_value_is_copied(self) -> None:
        defaults = extract_default_params(_form())

        assert set(defaults) == {"organism", "pValueCutoff"}

    def test_the_values_are_the_ones_the_form_offered(self) -> None:
        defaults = extract_default_params(_form())

        assert defaults["organism"] == "Plasmodium falciparum 3D7"
        assert defaults["pValueCutoff"] == "0.05"

    def test_a_param_the_form_left_empty_is_not_invented(self) -> None:
        # An absent default is the case creation rejects. A made-up value would
        # hide that rejection behind a wrong result.
        form = [WDKStringParam(name="organism", display_name="Organism"), *_form()[1:]]

        assert "organism" not in extract_default_params(form)


_SERVICE = "wdk"
_UNREADABLE = "Analysis form unavailable"


class _Counter:
    """Records how many times the analysis endpoint was reached."""

    def __init__(self) -> None:
        self.runs = 0

    async def __call__(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        self.runs += 1
        return {}


async def _unreadable_form(step_id: int, analysis_type: str) -> object:
    del step_id, analysis_type
    raise ExternalServiceError(_SERVICE, _UNREADABLE)


class TestAMissingFormStopsTheRun:
    @pytest.mark.asyncio
    async def test_the_analysis_is_not_run_without_its_parameters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        api = StrategyAPI(VEuPathDBClient("https://example.invalid/service"), "1")
        runs = _Counter()
        monkeypatch.setattr(api, "get_analysis_type", _unreadable_form)
        monkeypatch.setattr(api, "run_step_analysis", runs)

        with pytest.raises(ExternalServiceError):
            await EnrichmentService()._execute_analysis(api, 9, "go_process", 46)

        assert runs.runs == 0
