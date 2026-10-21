"""Formatting and parsing utilities for control-test evaluation."""

import json
from datetime import UTC, datetime, timedelta

import pydantic
from veupathdb import get_logger
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import (
    StrategyAPI,
    WDKStrategySummary,
    is_internal_wdk_strategy_name,
    strip_internal_wdk_strategy_name,
)

from veupathdb_mcp.controls.control_types import (
    ControlValueFormat,
    IntersectionConfig,
)

logger = get_logger(__name__)

CLEANUP_FAILURES = (VEuPathDBError, OSError, RuntimeError)

LEFTOVER_AGE = timedelta(days=2)

_WDK_TIME = pydantic.TypeAdapter(datetime)


def _encode_id_list(ids: list[str], fmt: ControlValueFormat) -> str:
    cleaned = [str(x).strip() for x in ids if str(x).strip()]
    if fmt == "newline":
        return "\n".join(cleaned)
    if fmt == "comma":
        return ",".join(cleaned)
    # json_list
    return json.dumps(cleaned)


async def delete_temp_strategy(api: StrategyAPI, strategy_id: int | None) -> None:
    """Delete a temporary WDK strategy, and log a refusal instead of raising it.

    A caller runs it in a ``finally`` block, so it never masks the first error.
    """
    if strategy_id is None:
        return
    try:
        await api.delete_strategy(strategy_id)
    except CLEANUP_FAILURES as exc:
        logger.warning(
            "Failed to delete temp WDK strategy during cleanup",
            temp_strategy_id=strategy_id,
            error=str(exc),
        )


async def _get_total_count_for_step(api: StrategyAPI, step_id: int) -> int | None:
    """Get totalCount for a step. Returns None on failure."""
    try:
        return await api.get_step_count(step_id)
    except (VEuPathDBError, RuntimeError) as exc:
        logger.debug(
            "Failed to get total count for step", step_id=step_id, error=str(exc)
        )
        return None


def leftover_strategy_ids(
    wdk_items: list[WDKStrategySummary], strategy_name: str
) -> list[int]:
    """The internal strategies a run under this name left on the account."""
    return [
        item.strategy_id
        for item in wdk_items
        if is_internal_wdk_strategy_name(item.name)
        and strip_internal_wdk_strategy_name(item.name).startswith(strategy_name)
    ]


def _created(item: WDKStrategySummary) -> datetime | None:
    try:
        created = _WDK_TIME.validate_python(item.created_time)
    except pydantic.ValidationError:
        return None
    return created if created.tzinfo is not None else created.replace(tzinfo=UTC)


def stale_leftover_ids(
    wdk_items: list[WDKStrategySummary], strategy_name: str
) -> list[int]:
    now = datetime.now(UTC)
    stale = {
        item.strategy_id
        for item in wdk_items
        if (created := _created(item)) is not None and now - created > LEFTOVER_AGE
    }
    return [i for i in leftover_strategy_ids(wdk_items, strategy_name) if i in stale]


async def delete_leftover_strategies(
    api: StrategyAPI,
    wdk_items: list[WDKStrategySummary],
    *,
    site_id: str,
    strategy_name: str,
) -> None:
    for strategy_id in stale_leftover_ids(wdk_items, strategy_name):
        try:
            await api.delete_strategy(strategy_id)
            logger.info(
                "Deleted leaked internal control-test WDK strategy",
                site_id=site_id,
                wdk_strategy_id=strategy_id,
            )
        except CLEANUP_FAILURES as e:
            logger.warning(
                "Failed to delete leaked internal control-test strategy",
                site_id=site_id,
                wdk_strategy_id=strategy_id,
                error=str(e),
            )


async def cleanup_internal_control_test_strategies(
    api: StrategyAPI,
    wdk_items: list[WDKStrategySummary],
    config: IntersectionConfig,
) -> None:
    """Delete leaked internal control-test strategies from a WDK item list.

    Callers fetch the item list themselves (via ``api.list_strategies()``),
    then pass it here with the config a run was given. The config carries the
    name the run wrote, so a match can never drift from a write.
    """
    await delete_leftover_strategies(
        api,
        wdk_items,
        site_id=config.site_id,
        strategy_name=config.internal_strategy_name,
    )
