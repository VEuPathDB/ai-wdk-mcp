"""Counting a plan WDK has not built yet, and what it leaves behind."""

from typing import Any

import pytest
from veupathdb.domain.parameters.values import StringValue
from veupathdb.domain.strategy.ast import StrategyStepNode
from veupathdb.domain.strategy.ops import CombineOp
from veupathdb.domain.strategy.strategy_ast import StrategyAst
from veupathdb.errors import VEuPathDBError, VEuPathDBErrorCode
from veupathdb.json_types import JSONObject
from veupathdb.wdk.wdk_models import (
    CombinedStepSpec,
    NewStepSpec,
    WDKAnswer,
    WDKAnswerMeta,
    WDKIdentifier,
    WDKSearchConfig,
    WDKStep,
    WDKStepTree,
    WDKStrategyDetails,
)

from veupathdb_mcp.wdk.plan_counts import (
    DEFAULT_PLAN_COUNTS_STRATEGY_NAME,
    compute_plan_step_counts,
    is_leaf_only_plan,
)


def _wdk_refusal(title: str) -> VEuPathDBError:
    return VEuPathDBError(VEuPathDBErrorCode.WDK_ERROR, title, status=500)


REFUSAL = _wdk_refusal("WDK refused the step")


def _leaf(
    step_id: str, search_name: str = "GenesByMolecularWeight"
) -> StrategyStepNode:
    return StrategyStepNode(
        id=step_id,
        search_name=search_name,
        parameters={"min_molecular_weight": StringValue(value="10000")},
    )


def _leaf_only_plan() -> StrategyAst:
    return StrategyAst(record_type="transcript", root=_leaf("kinase"))


def _combine_plan() -> StrategyAst:
    return StrategyAst(
        record_type="transcript",
        root=StrategyStepNode(
            id="combine",
            search_name="__combine__",
            operator=CombineOp.INTERSECT,
            primary_input=_leaf("kinase"),
            secondary_input=_leaf("secreted", "GenesBySignalPeptide"),
        ),
    )


class _FakeClient:
    """Answers the anonymous report endpoint with a count per search name."""

    def __init__(self, counts: dict[str, int | Exception]) -> None:
        self._counts = counts
        self.report_configs: list[JSONObject | None] = []

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        self.report_configs.append(report_config)
        answer = self._counts[search_name]
        if isinstance(answer, Exception):
            raise answer
        return WDKAnswer(meta=WDKAnswerMeta(total_count=answer), records=[])


class _FakeStrategyAPI:
    """Hands out step ids in order and reports the sizes it was given."""

    def __init__(
        self,
        client: _FakeClient,
        *,
        estimated_sizes: dict[int, int] | None = None,
        refuse_step: str | None = None,
    ) -> None:
        self.client = client
        self._estimated_sizes = estimated_sizes or {}
        self._refuse_step = refuse_step
        self._next_id = 100
        self.created_strategy_names: list[str] = []
        self.deleted_strategies: list[int] = []
        self.created_step_trees: list[WDKStepTree] = []

    def _mint(self) -> WDKIdentifier:
        self._next_id += 1
        return WDKIdentifier(id=self._next_id)

    async def create_step(
        self, spec: NewStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        if spec.search_name == self._refuse_step:
            raise REFUSAL
        return self._mint()

    async def create_combined_step(
        self, spec: CombinedStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        return self._mint()

    async def create_strategy(
        self,
        step_tree: WDKStepTree,
        name: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> WDKIdentifier:
        self.created_strategy_names.append(name)
        self.created_step_trees.append(step_tree)
        return WDKIdentifier(id=7000)

    async def get_strategy(
        self, strategy_id: int, user_id: str | None = None
    ) -> WDKStrategyDetails:
        return WDKStrategyDetails(
            strategy_id=strategy_id,
            name="internal",
            root_step_id=103,
            step_tree=WDKStepTree(step_id=103),
            steps={
                str(step_id): WDKStep(
                    id=step_id,
                    search_name="GenesByMolecularWeight",
                    search_config=WDKSearchConfig(),
                    estimated_size=size,
                )
                for step_id, size in self._estimated_sizes.items()
            },
        )

    async def delete_strategy(
        self, strategy_id: int, user_id: str | None = None
    ) -> None:
        self.deleted_strategies.append(strategy_id)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> _FakeStrategyAPI:
    built = _FakeStrategyAPI(
        _FakeClient({"GenesByMolecularWeight": 587, "GenesBySignalPeptide": 240}),
        estimated_sizes={101: 587, 102: 240, 103: 91},
    )
    monkeypatch.setattr(
        "veupathdb_mcp.wdk.plan_counts.get_strategy_api", lambda site_id: built
    )
    return built


class TestALeafOnlyPlanNeedsNoStrategy:
    def test_a_plan_of_searches_is_leaf_only(self) -> None:
        assert is_leaf_only_plan(_leaf_only_plan().root)

    def test_a_plan_with_a_combine_is_not(self) -> None:
        assert not is_leaf_only_plan(_combine_plan().root)

    async def test_the_count_comes_from_the_anonymous_report(
        self, api: _FakeStrategyAPI
    ) -> None:
        counts = await compute_plan_step_counts(_leaf_only_plan(), "plasmodb")

        assert counts == {"kinase": 587}

    async def test_the_report_asks_for_no_records(self, api: _FakeStrategyAPI) -> None:
        await compute_plan_step_counts(_leaf_only_plan(), "plasmodb")

        assert api.client.report_configs == [
            {"pagination": {"offset": 0, "numRecords": 0}}
        ]

    async def test_no_strategy_is_created(self, api: _FakeStrategyAPI) -> None:
        await compute_plan_step_counts(_leaf_only_plan(), "plasmodb")

        assert api.created_strategy_names == []

    async def test_a_refused_search_counts_as_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        built = _FakeStrategyAPI(
            _FakeClient({"GenesByMolecularWeight": _wdk_refusal("WDK is down")})
        )
        monkeypatch.setattr(
            "veupathdb_mcp.wdk.plan_counts.get_strategy_api", lambda site_id: built
        )

        counts = await compute_plan_step_counts(_leaf_only_plan(), "plasmodb")

        assert counts == {"kinase": None}


class TestAPlanWithACombineUsesATemporaryStrategy:
    async def test_every_step_reports_its_estimated_size(
        self, api: _FakeStrategyAPI
    ) -> None:
        counts = await compute_plan_step_counts(_combine_plan(), "plasmodb")

        assert counts == {"kinase": 587, "secreted": 240, "combine": 91}

    async def test_the_tree_carries_the_wdk_step_ids(
        self, api: _FakeStrategyAPI
    ) -> None:
        await compute_plan_step_counts(_combine_plan(), "plasmodb")

        assert api.created_step_trees[0].model_dump(
            by_alias=True, exclude_none=True
        ) == {
            "stepId": 103,
            "primaryInput": {"stepId": 101},
            "secondaryInput": {"stepId": 102},
        }

    async def test_the_temporary_strategy_is_deleted(
        self, api: _FakeStrategyAPI
    ) -> None:
        await compute_plan_step_counts(_combine_plan(), "plasmodb")

        assert api.deleted_strategies == [7000]

    async def test_the_caller_names_the_temporary_strategy(
        self, api: _FakeStrategyAPI
    ) -> None:
        await compute_plan_step_counts(
            _combine_plan(), "plasmodb", strategy_name="Pathfinder step counts"
        )

        assert api.created_strategy_names == ["Pathfinder step counts"]

    async def test_the_default_name_names_no_product(
        self, api: _FakeStrategyAPI
    ) -> None:
        await compute_plan_step_counts(_combine_plan(), "plasmodb")

        assert api.created_strategy_names == [DEFAULT_PLAN_COUNTS_STRATEGY_NAME]
        assert "pathfinder" not in DEFAULT_PLAN_COUNTS_STRATEGY_NAME.lower()

    async def test_a_step_wdk_refused_leaves_every_count_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        built = _FakeStrategyAPI(_FakeClient({}), refuse_step="GenesBySignalPeptide")
        monkeypatch.setattr(
            "veupathdb_mcp.wdk.plan_counts.get_strategy_api", lambda site_id: built
        )

        counts = await compute_plan_step_counts(_combine_plan(), "plasmodb")

        assert counts == {"kinase": None, "secreted": None, "combine": None}
        assert built.created_strategy_names == []
