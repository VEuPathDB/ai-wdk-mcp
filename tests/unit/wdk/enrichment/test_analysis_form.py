"""An analysis form supplies the parameters analysis creation will not fill.

Creation validates with no fill, so a form the service cannot read stops the
run. Running with no parameters is a rejection, not a degraded run.
"""

from __future__ import annotations

import pytest
from veupathdb.errors import ExternalServiceError
from veupathdb.wdk import StrategyAPI, VEuPathDBClient

from veupathdb_mcp.wdk.enrichment import EnrichmentService

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
