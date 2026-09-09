"""The WDK step tree a plan tree folds into."""

from veupathdb.domain.strategy.ast import StrategyStepNode
from veupathdb.domain.strategy.tree import fold
from veupathdb.errors import VEuPathDBError, VEuPathDBErrorCode
from veupathdb.wdk.wdk_models import WDKStepTree

__all__ = ["MissingWDKStepIdError", "build_wdk_step_tree"]


class MissingWDKStepIdError(VEuPathDBError):
    """A step of the tree reached no WDK step id."""

    def __init__(self, step_id: str) -> None:
        super().__init__(
            code=VEuPathDBErrorCode.INTERNAL_ERROR,
            title="Step tree is incomplete",
            status=500,
            detail=f"Step '{step_id}' has no WDK step id",
        )


def build_wdk_step_tree(
    root: StrategyStepNode,
    wdk_step_ids: dict[str, int],
) -> WDKStepTree:
    """The WDK step tree of a plan, with the plan's ids replaced by WDK ids.

    :raises MissingWDKStepIdError: When a step of the tree reached no WDK id.
    """

    def node(step: StrategyStepNode, inputs: list[WDKStepTree]) -> WDKStepTree:
        wdk_id = wdk_step_ids.get(step.id)
        if wdk_id is None:
            raise MissingWDKStepIdError(step.id)
        slots: list[WDKStepTree | None] = [*inputs, None, None]
        return WDKStepTree(
            step_id=wdk_id, primary_input=slots[0], secondary_input=slots[1]
        )

    return fold(root, node)
