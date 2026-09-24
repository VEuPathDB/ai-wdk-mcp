"""The WDK calls one control-intersection run makes, answered in memory."""

from __future__ import annotations

from typing import Any

import pytest
from tests._support.recorded_searches import gene_list_search
from veupathdb.domain import WDKRecordIdPart
from veupathdb.wdk import (
    CombinedStepSpec,
    NewStepSpec,
    WDKAnswer,
    WDKAnswerMeta,
    WDKDatasetConfigIdList,
    WDKFilterValue,
    WDKIdentifier,
    WDKRecordInstance,
    WDKSearchResponse,
    WDKStepTree,
    WDKStrategySummary,
)


class FakeCleanupAPI:
    """The one call a cleanup makes. Every call this fake answers is named in order."""

    def __init__(self) -> None:
        self.deleted: list[int] = []
        self.calls: list[str] = []

    async def delete_strategy(
        self, strategy_id: int, user_id: str | None = None
    ) -> None:
        self.calls.append("delete_strategy")
        self.deleted.append(strategy_id)


class _SearchDetailsClient:
    """The catalog read a controls run makes, answered with GeneByLocusTag."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def get_search_details(
        self, record_type: str, search_name: str, *, expand_params: bool = False
    ) -> WDKSearchResponse:
        self._calls.append("get_search_details")
        return gene_list_search()


class RunFakeAPI(FakeCleanupAPI):
    """Enough of the strategy API for one intersection run."""

    def __init__(
        self, step_count: int = 12, answer_ids: tuple[str, ...] = ("PF3D7_0100100",)
    ) -> None:
        super().__init__()
        self.created_strategy_names: list[str] = []
        self.answer_calls: list[int] = []
        self.answer_view_filters: list[list[WDKFilterValue] | None] = []
        self.datasets: list[list[str]] = []
        self.steps: list[NewStepSpec] = []
        self.combines: list[CombinedStepSpec] = []
        self.trees: list[WDKStepTree] = []
        self.client = _SearchDetailsClient(self.calls)
        self._step_count = step_count
        self._answer_ids = answer_ids
        self._next_id = 200

    async def create_dataset(self, config: WDKDatasetConfigIdList) -> int:
        self.calls.append("create_dataset")
        self.datasets.append(list(config.source_content.ids))
        return 4242

    async def create_step(
        self, spec: NewStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        self.calls.append("create_step")
        self.steps.append(spec)
        self._next_id += 1
        return WDKIdentifier(id=self._next_id)

    async def create_combined_step(
        self, spec: CombinedStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        self.calls.append("create_combined_step")
        self.combines.append(spec)
        self._next_id += 1
        return WDKIdentifier(id=self._next_id)

    async def create_strategy(
        self,
        step_tree: WDKStepTree,
        name: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> WDKIdentifier:
        self.calls.append("create_strategy")
        self.created_strategy_names.append(name)
        self.trees.append(step_tree)
        return WDKIdentifier(id=8000)

    async def get_step_count(self, step_id: int) -> int:
        self.calls.append("get_step_count")
        return self._step_count

    async def get_step_answer(
        self,
        step_id: int,
        attributes: list[str] | None = None,
        pagination: dict[str, int] | None = None,
        *,
        view_filters: list[WDKFilterValue] | None = None,
    ) -> WDKAnswer:
        del attributes, pagination
        self.calls.append("get_step_answer")
        self.answer_calls.append(step_id)
        self.answer_view_filters.append(view_filters)
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
        self.calls.append("list_strategies")
        return []


def patch_control_account(
    monkeypatch: pytest.MonkeyPatch, api: RunFakeAPI, record_type: str = "transcript"
) -> RunFakeAPI:
    """Route a control run at the given fake, and answer the record-type lookup."""
    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.get_strategy_api", lambda site_id: api
    )

    async def _record_type(ctx: object) -> str:
        return record_type

    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.find_record_type_for_search", _record_type
    )
    return api


def patch_control_run(
    monkeypatch: pytest.MonkeyPatch, api: RunFakeAPI, record_type: str = "transcript"
) -> RunFakeAPI:
    """Route a control run at the given fake, and answer the catalog reads."""
    patch_control_account(monkeypatch, api, record_type)

    async def _param_type(*args: object, **kwargs: object) -> str:
        return "string"

    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.resolve_controls_param_type", _param_type
    )
    return api
