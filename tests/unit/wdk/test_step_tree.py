"""The WDK step tree a plan folds into, and the id it refuses to invent."""

import pytest
from veupathdb.domain.strategy.ast import StrategyStepNode
from veupathdb.domain.strategy.ops import CombineOp
from veupathdb.errors import VEuPathDBError, VEuPathDBErrorCode

from veupathdb_mcp.wdk.step_tree import MissingWDKStepIdError, build_wdk_step_tree


def _leaf(step_id: str) -> StrategyStepNode:
    return StrategyStepNode(id=step_id, search_name="GenesByMolecularWeight")


class TestSlotOrder:
    def test_a_search_holds_no_input(self) -> None:
        tree = build_wdk_step_tree(_leaf("kinase"), {"kinase": 41})

        assert tree.step_id == 41
        assert tree.primary_input is None
        assert tree.secondary_input is None

    def test_a_transform_fills_the_primary_slot_only(self) -> None:
        root = StrategyStepNode(
            id="orthologs",
            search_name="GenesByOrthologPattern",
            primary_input=_leaf("kinase"),
        )

        tree = build_wdk_step_tree(root, {"orthologs": 50, "kinase": 41})

        assert tree.step_id == 50
        assert tree.primary_input is not None
        assert tree.primary_input.step_id == 41
        assert tree.secondary_input is None

    def test_a_combine_fills_both_slots_in_order(self) -> None:
        root = StrategyStepNode(
            id="combine",
            search_name="__combine__",
            operator=CombineOp.INTERSECT,
            primary_input=_leaf("kinase"),
            secondary_input=_leaf("secreted"),
        )

        tree = build_wdk_step_tree(root, {"combine": 60, "kinase": 41, "secreted": 42})

        assert tree.step_id == 60
        assert tree.primary_input is not None
        assert tree.primary_input.step_id == 41
        assert tree.secondary_input is not None
        assert tree.secondary_input.step_id == 42


class TestAMissingIdIsRefused:
    def test_a_missing_root_id_is_refused(self) -> None:
        with pytest.raises(MissingWDKStepIdError) as excinfo:
            build_wdk_step_tree(_leaf("kinase"), {})

        assert "kinase" in str(excinfo.value)

    def test_a_missing_input_id_is_refused(self) -> None:
        root = StrategyStepNode(
            id="combine",
            search_name="__combine__",
            operator=CombineOp.INTERSECT,
            primary_input=_leaf("kinase"),
            secondary_input=_leaf("secreted"),
        )

        with pytest.raises(MissingWDKStepIdError) as excinfo:
            build_wdk_step_tree(root, {"combine": 60, "kinase": 41})

        assert "secreted" in str(excinfo.value)

    def test_the_refusal_is_a_veupathdb_error(self) -> None:
        with pytest.raises(VEuPathDBError) as excinfo:
            build_wdk_step_tree(_leaf("kinase"), {})

        assert excinfo.value.code == VEuPathDBErrorCode.INTERNAL_ERROR
        assert excinfo.value.status == 500
