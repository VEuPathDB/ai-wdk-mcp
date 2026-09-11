"""The WDK calls one control-intersection run makes, answered in memory."""

from __future__ import annotations

from typing import Any

import pytest
from veupathdb.domain import WDKRecordIdPart
from veupathdb.wdk import (
    CombinedStepSpec,
    NewStepSpec,
    WDKAnswer,
    WDKAnswerMeta,
    WDKIdentifier,
    WDKRecordInstance,
    WDKStepTree,
    WDKStrategySummary,
)


class FakeCleanupAPI:
    """The one call a cleanup makes."""

    def __init__(self) -> None:
        self.deleted: list[int] = []

    async def delete_strategy(
        self, strategy_id: int, user_id: str | None = None
    ) -> None:
        self.deleted.append(strategy_id)


class RunFakeAPI(FakeCleanupAPI):
    """Enough of the strategy API for one intersection run."""

    def __init__(
        self, step_count: int = 12, answer_ids: tuple[str, ...] = ("PF3D7_0100100",)
    ) -> None:
        super().__init__()
        self.created_strategy_names: list[str] = []
        self.answer_calls: list[int] = []
        self._step_count = step_count
        self._answer_ids = answer_ids
        self._next_id = 200

    async def create_step(
        self, spec: NewStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        self._next_id += 1
        return WDKIdentifier(id=self._next_id)

    async def create_combined_step(
        self, spec: CombinedStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        self._next_id += 1
        return WDKIdentifier(id=self._next_id)

    async def create_strategy(
        self,
        step_tree: WDKStepTree,
        name: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> WDKIdentifier:
        self.created_strategy_names.append(name)
        return WDKIdentifier(id=8000)

    async def get_step_count(self, step_id: int) -> int:
        return self._step_count

    async def get_step_answer(self, step_id: int, **kwargs: Any) -> WDKAnswer:
        self.answer_calls.append(step_id)
        return WDKAnswer(
            meta=WDKAnswerMeta(total_count=len(self._answer_ids)),
            records=[
                WDKRecordInstance(
                    display_name=gene_id,
                    id=[WDKRecordIdPart(name="source_id", value=gene_id)],
                )
                for gene_id in self._answer_ids
            ],
        )

    async def list_strategies(self) -> list[WDKStrategySummary]:
        return []


def patch_control_run(monkeypatch: pytest.MonkeyPatch, api: RunFakeAPI) -> RunFakeAPI:
    """Route a control run at the given fake, and answer the catalog reads."""
    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.get_strategy_api", lambda site_id: api
    )

    async def _record_type(ctx: object) -> str:
        return "transcript"

    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.find_record_type_for_search", _record_type
    )

    async def _param_type(*args: object, **kwargs: object) -> str:
        return "string"

    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.resolve_controls_param_type", _param_type
    )
    return api
