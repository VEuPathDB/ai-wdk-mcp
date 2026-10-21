"""The WDK calls one control-intersection run makes, answered in memory."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from tests._support.recorded_searches import gene_list_search
from veupathdb.domain import WDKRecordIdPart
from veupathdb.errors import WDKError
from veupathdb.wdk import (
    CombinedStepSpec,
    NewStepSpec,
    WDKAnswer,
    WDKAnswerMeta,
    WDKDatasetConfigIdList,
    WDKFilterValue,
    WDKIdentifier,
    WDKRecordInstance,
    WDKSearchConfig,
    WDKSearchResponse,
    WDKStep,
    WDKStepTree,
    WDKStrategyDetails,
    WDKStrategySummary,
    tag_internal_wdk_strategy_name,
    walk_wdk_step_tree,
)

from veupathdb_mcp.wdk.helpers import extract_pk

WDK_TIME = "%Y-%m-%dT%H:%M:%S"
TESTED_STEP = 4242
STEP_STRATEGY = 9000
COPY_OFFSET = 1000


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

    async def delete_step(self, step_id: int, *, user_id: str | None = None) -> None:
        self.calls.append("delete_step")


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


def wdk_time(age: timedelta) -> str:
    """The time WDK lists for a strategy created ``age`` ago, in its own format."""
    return (datetime.now(UTC) - age).strftime(WDK_TIME)


def gene_records(*gene_ids: str) -> list[WDKRecordInstance]:
    """Transcript records keyed by their gene id, as a step report serves them."""
    return [
        WDKRecordInstance(
            display_name=gene_id,
            id=[WDKRecordIdPart(name="gene_source_id", value=gene_id)],
        )
        for gene_id in gene_ids
    ]


def _copied(tree: WDKStepTree) -> WDKStepTree:
    return WDKStepTree(
        step_id=tree.step_id + COPY_OFFSET,
        primary_input=None
        if tree.primary_input is None
        else _copied(tree.primary_input),
        secondary_input=(
            None if tree.secondary_input is None else _copied(tree.secondary_input)
        ),
    )


@dataclass(frozen=True)
class Faults:
    """Calls the site refuses, writes whose answer waits for ``release``, and
    writes the site makes whose answer is lost."""

    fail: frozenset[str] = frozenset()
    hold: frozenset[str] = frozenset()
    lose: frozenset[str] = frozenset()


NO_FAULTS = Faults()


class StepRunFakeAPI(RunFakeAPI):
    """A step built inside a strategy, whose records only an intersection reveals.

    The combine answers the step's records whose gene id is among the uploaded
    controls, as the site's INTERSECT does. The account keeps every step no
    strategy holds and every strategy not deleted.
    """

    def __init__(
        self,
        records: list[WDKRecordInstance],
        *,
        record_class_name: str = "transcript",
        strategy_tree: WDKStepTree | None = None,
        strategy_id: int | None = STEP_STRATEGY,
        faults: Faults = NO_FAULTS,
    ) -> None:
        super().__init__(step_count=len(records))
        self.records = records
        self.record_class_name = record_class_name
        self.strategy_tree = strategy_tree or WDKStepTree(step_id=TESTED_STEP)
        self.strategy_id = strategy_id
        self.count_calls: list[int] = []
        self.answer_paginations: list[dict[str, int] | None] = []
        self.deleted_steps: list[int] = []
        self.unattached: list[int] = []
        self.strategies: dict[int, frozenset[int]] = {}
        self.deletes_in_flight = 0
        self.most_deletes_in_flight = 0
        self.faults = faults
        self.reached = {call: asyncio.Event() for call in faults.hold}
        self.release = {call: asyncio.Event() for call in faults.hold}
        self.strategy_deleted = asyncio.Event()
        self.strategy_names: dict[int, str] = {}
        self.strategy_created: dict[int, str] = {}
        self._next_strategy = 8000

    def holds(self) -> tuple[list[int], list[int]]:
        """The steps no strategy holds, and the strategies not deleted."""
        return sorted(self.unattached), sorted(self.strategies)

    def _refuse(self, call: str) -> None:
        if call in self.faults.fail:
            msg = f"{call} refused"
            raise WDKError(msg, status=502)

    async def _answer(self, call: str) -> None:
        if call in self.faults.hold:
            self.reached[call].set()
            await self.release[call].wait()
        if call in self.faults.lose:
            msg = f"the answer to {call} was lost"
            raise WDKError(msg, status=502)

    async def create_step(
        self, spec: NewStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        self._refuse("create_step")
        created = await super().create_step(spec, record_type, user_id)
        self.unattached.append(created.id)
        await self._answer("create_step")
        return created

    async def create_combined_step(
        self, spec: CombinedStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        self._refuse("create_combined_step")
        created = await super().create_combined_step(spec, record_type, user_id)
        self.unattached.append(created.id)
        await self._answer("create_combined_step")
        return created

    async def create_strategy(
        self,
        step_tree: WDKStepTree,
        name: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> WDKIdentifier:
        self._refuse("create_strategy")
        self.calls.append("create_strategy")
        self.created_strategy_names.append(name)
        self.trees.append(step_tree)
        created = WDKIdentifier(id=self._next_strategy)
        self._next_strategy += 1
        held = frozenset(node.step_id for node in walk_wdk_step_tree(step_tree))
        self.unattached = [step for step in self.unattached if step not in held]
        self.strategies[created.id] = held
        self.strategy_names[created.id] = tag_internal_wdk_strategy_name(name)
        self.strategy_created[created.id] = wdk_time(timedelta())
        await self._answer("create_strategy")
        return created

    async def list_strategies(self) -> list[WDKStrategySummary]:
        self.calls.append("list_strategies")
        return [
            WDKStrategySummary(
                strategy_id=strategy_id,
                name=self.strategy_names[strategy_id],
                root_step_id=min(held) if held else 1,
                created_time=self.strategy_created[strategy_id],
            )
            for strategy_id, held in self.strategies.items()
        ]

    def seed_strategy(self, strategy_id: int, name: str, created_time: str) -> None:
        """An internal strategy another run wrote, created at ``created_time``."""
        self.strategies[strategy_id] = frozenset()
        self.strategy_names[strategy_id] = tag_internal_wdk_strategy_name(name)
        self.strategy_created[strategy_id] = created_time

    async def delete_strategy(
        self, strategy_id: int, user_id: str | None = None
    ) -> None:
        self.calls.append("delete_strategy")
        await self._answer("delete_strategy")
        self._refuse("delete_strategy")
        self.deleted.append(strategy_id)
        self.strategies.pop(strategy_id, None)
        self.strategy_deleted.set()

    async def delete_step(self, step_id: int, *, user_id: str | None = None) -> None:
        self.calls.append("delete_step")
        self.deletes_in_flight += 1
        self.most_deletes_in_flight = max(
            self.most_deletes_in_flight, self.deletes_in_flight
        )
        await asyncio.sleep(0)
        self.deletes_in_flight -= 1
        self._refuse("delete_step")
        if any(step_id in held for held in self.strategies.values()):
            msg = "Steps that are part of strategies cannot be deleted."
            raise WDKError(msg, status=409)
        self.deleted_steps.append(step_id)
        if step_id in self.unattached:
            self.unattached.remove(step_id)

    async def find_step(self, step_id: int, user_id: str | None = None) -> WDKStep:
        self.calls.append("find_step")
        return WDKStep(
            id=step_id,
            search_name="GenesByMolecularWeight",
            search_config=WDKSearchConfig(),
            record_class_name=self.record_class_name,
            strategy_id=self.strategy_id,
        )

    async def get_strategy(
        self, strategy_id: int, user_id: str | None = None
    ) -> WDKStrategyDetails:
        self.calls.append("get_strategy")
        return WDKStrategyDetails(
            strategy_id=strategy_id,
            name="kinases",
            root_step_id=self.strategy_tree.step_id,
            step_tree=self.strategy_tree,
        )

    async def get_duplicated_step_tree(
        self, strategy_id: int, user_id: str | None = None
    ) -> WDKStepTree:
        self.calls.append("get_duplicated_step_tree")
        self._refuse("get_duplicated_step_tree")
        copy = _copied(self.strategy_tree)
        self.unattached.extend(node.step_id for node in walk_wdk_step_tree(copy))
        await self._answer("get_duplicated_step_tree")
        return copy

    async def get_step_count(self, step_id: int) -> int:
        self.calls.append("get_step_count")
        self.count_calls.append(step_id)
        return len(self.records)

    async def get_step_answer(
        self,
        step_id: int,
        attributes: list[str] | None = None,
        pagination: dict[str, int] | None = None,
        *,
        view_filters: list[WDKFilterValue] | None = None,
    ) -> WDKAnswer:
        del attributes
        self.calls.append("get_step_answer")
        self.answer_calls.append(step_id)
        self.answer_paginations.append(pagination)
        self.answer_view_filters.append(view_filters)
        uploaded = set(self.datasets[-1])
        returned = [r for r in self.records if extract_pk(r) in uploaded]
        return WDKAnswer(
            meta=WDKAnswerMeta(total_count=len(returned)), records=returned
        )


def patch_step_run(
    monkeypatch: pytest.MonkeyPatch, api: StepRunFakeAPI
) -> StepRunFakeAPI:
    """Route a step control run at the given fake, whose controls upload a dataset."""
    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.get_strategy_api", lambda site_id: api
    )

    async def _param_type(*args: object, **kwargs: object) -> str:
        return "input-dataset"

    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.resolve_controls_param_type", _param_type
    )
    return api
