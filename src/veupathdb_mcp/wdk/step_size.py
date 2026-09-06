"""How many records a built WDK step holds."""

from dataclasses import dataclass

from veupathdb.wdk.factory import get_strategy_api


@dataclass
class StepCountResult:
    """Outcome of a step count lookup."""

    step_id: int
    count: int


async def get_estimated_size_for_site(
    site_id: str,
    wdk_step_id: int,
    wdk_strategy_id: int | None = None,
) -> StepCountResult:
    """Get the result count for a built WDK step.

    The strategy payload carries ``estimatedSize`` and is the cheaper read; a
    direct step count query answers when it does not.

    :raises WDKError: On WDK API errors.
    """
    api = get_strategy_api(site_id)
    if wdk_strategy_id is not None:
        strategy = await api.get_strategy(wdk_strategy_id)
        step = strategy.steps.get(str(wdk_step_id))
        if step is not None and step.estimated_size is not None:
            return StepCountResult(step_id=wdk_step_id, count=step.estimated_size)

    count = await api.get_step_count(wdk_step_id)
    return StepCountResult(step_id=wdk_step_id, count=count)
