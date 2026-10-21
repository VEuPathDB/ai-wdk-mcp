"""The steps and the strategy one control run writes, deleted when the run ends."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager

from veupathdb import get_logger
from veupathdb.wdk import (
    StrategyAPI,
    WDKIdentifier,
    WDKStepTree,
    walk_wdk_step_tree,
)

from veupathdb_mcp.controls.control_helpers import (
    CLEANUP_FAILURES,
    delete_temp_strategy,
)

logger = get_logger(__name__)

_CLEANUPS: set[asyncio.Task[None]] = set()


async def _settled[T](task: asyncio.Task[T] | None) -> T | None:
    if task is None:
        return None
    await asyncio.wait({task})
    if task.cancelled() or task.exception() is not None:
        return None
    return task.result()


async def _one_step(write: Awaitable[WDKIdentifier]) -> WDKStepTree:
    return WDKStepTree(step_id=(await write).id)


class RunWrites:
    def __init__(self, api: StrategyAPI) -> None:
        self._api = api
        self._steps: list[asyncio.Task[WDKStepTree]] = []
        self._strategy: asyncio.Task[WDKIdentifier] | None = None
        self._held: frozenset[int] = frozenset()
        self._gone: set[int] = set()
        self._run_id = uuid.uuid4().hex[:12]

    async def _made(self, write: Awaitable[WDKStepTree]) -> WDKStepTree:
        task = asyncio.ensure_future(write)
        self._steps.append(task)
        return await asyncio.shield(task)

    async def step(self, write: Awaitable[WDKIdentifier]) -> int:
        return (await self._made(_one_step(write))).step_id

    async def steps(self, write: Awaitable[WDKStepTree]) -> WDKStepTree:
        return await self._made(write)

    async def strategy(self, tree: WDKStepTree, name: str) -> int:
        self._held = frozenset(node.step_id for node in walk_wdk_step_tree(tree))
        task = asyncio.ensure_future(
            self._api.create_strategy(
                step_tree=tree,
                name=f"{name} {self._run_id}",
                description=None,
                is_internal=True,
            )
        )
        self._strategy = task
        return (await asyncio.shield(task)).id

    async def delete_steps(self, step_ids: list[int]) -> None:
        for step_id in step_ids:
            await self._delete_step(step_id)

    async def _delete_step(self, step_id: int) -> None:
        try:
            await self._api.delete_step(step_id)
        except CLEANUP_FAILURES as exc:
            logger.warning(
                "Failed to delete a control-run step", step_id=step_id, error=str(exc)
            )
        else:
            self._gone.add(step_id)

    async def clean(self) -> None:
        strategy = await _settled(self._strategy)
        held = frozenset() if strategy is None else self._held
        if strategy is not None:
            await delete_temp_strategy(self._api, strategy.id)
        for task in reversed(self._steps):
            tree = await _settled(task)
            if tree is None:
                continue
            await self.delete_steps(
                [
                    node.step_id
                    for node in reversed(walk_wdk_step_tree(tree))
                    if node.step_id not in held and node.step_id not in self._gone
                ]
            )


def _cleanup_ended(task: asyncio.Task[None]) -> None:
    _CLEANUPS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("A control-run cleanup failed", error=str(task.exception()))


@asynccontextmanager
async def run_writes(api: StrategyAPI) -> AsyncIterator[RunWrites]:
    writes = RunWrites(api)
    try:
        yield writes
    finally:
        cleanup = asyncio.ensure_future(writes.clean())
        _CLEANUPS.add(cleanup)
        cleanup.add_done_callback(_cleanup_ended)
        await asyncio.shield(cleanup)
