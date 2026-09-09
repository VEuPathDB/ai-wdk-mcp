"""The name a control run writes into WDK is the name its cleanup matches."""

from typing import Any

import pytest
from veupathdb.wdk.strategy_api.helpers import tag_internal_wdk_strategy_name
from veupathdb.wdk.wdk_models import (
    CombinedStepSpec,
    NewStepSpec,
    WDKAnswer,
    WDKAnswerMeta,
    WDKIdentifier,
    WDKRecordInstance,
    WDKStepTree,
    WDKStrategySummary,
)

from veupathdb_mcp.controls.control_helpers import (
    cleanup_internal_control_test_strategies,
)
from veupathdb_mcp.controls.control_tests import run_positive_negative_controls
from veupathdb_mcp.controls.control_types import (
    DEFAULT_CONTROL_TEST_STRATEGY_NAME,
    IntersectionConfig,
)


class _FakeStrategyAPI:
    def __init__(self) -> None:
        self.deleted: list[int] = []

    async def delete_strategy(
        self, strategy_id: int, user_id: str | None = None
    ) -> None:
        self.deleted.append(strategy_id)


def _summary(strategy_id: int, name: str, **kwargs: Any) -> WDKStrategySummary:
    return WDKStrategySummary(
        strategy_id=strategy_id, name=name, root_step_id=1, **kwargs
    )


def _internal(strategy_id: int, display_name: str) -> WDKStrategySummary:
    return _summary(strategy_id, tag_internal_wdk_strategy_name(display_name))


def _config(**kwargs: Any) -> IntersectionConfig:
    return IntersectionConfig(
        site_id="plasmodb",
        record_type="transcript",
        target_search_name="GenesByMolecularWeight",
        target_parameters={},
        controls_search_name="GeneByLocusTag",
        controls_param_name="ds_gene_ids",
        **kwargs,
    )


class TestTheDefaultNamesNoProduct:
    def test_the_default_is_neutral(self) -> None:
        assert DEFAULT_CONTROL_TEST_STRATEGY_NAME == "control test"

    def test_a_config_carries_the_default(self) -> None:
        assert _config().internal_strategy_name == DEFAULT_CONTROL_TEST_STRATEGY_NAME


class TestCleanupMatchesTheNameTheRunWrote:
    async def test_the_default_name_is_recognised(self) -> None:
        api = _FakeStrategyAPI()

        await cleanup_internal_control_test_strategies(
            api,
            [_internal(11, "control test 3")],
            _config(),
        )

        assert api.deleted == [11]

    async def test_a_caller_supplied_name_is_recognised(self) -> None:
        api = _FakeStrategyAPI()

        await cleanup_internal_control_test_strategies(
            api,
            [_internal(12, "Pathfinder control test")],
            _config(internal_strategy_name="Pathfinder control test"),
        )

        assert api.deleted == [12]

    async def test_another_run_s_name_is_left_alone(self) -> None:
        api = _FakeStrategyAPI()

        await cleanup_internal_control_test_strategies(
            api,
            [_internal(13, "Pathfinder control test")],
            _config(),
        )

        assert api.deleted == []

    async def test_a_public_strategy_is_never_deleted(self) -> None:
        api = _FakeStrategyAPI()

        await cleanup_internal_control_test_strategies(
            api,
            [_summary(14, "control test")],
            _config(),
        )

        assert api.deleted == []


class _RunFakeAPI(_FakeStrategyAPI):
    """Enough of the strategy API for one intersection run."""

    def __init__(self) -> None:
        super().__init__()
        self.created_strategy_names: list[str] = []
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
        return 12

    async def get_step_answer(self, step_id: int, **kwargs: Any) -> WDKAnswer:
        return WDKAnswer(
            meta=WDKAnswerMeta(total_count=1),
            records=[WDKRecordInstance(display_name="PF3D7_0100100")],
        )

    async def list_strategies(self) -> list[WDKStrategySummary]:
        return []


@pytest.fixture
def run_api(monkeypatch: pytest.MonkeyPatch) -> _RunFakeAPI:
    built = _RunFakeAPI()
    monkeypatch.setattr(
        "veupathdb_mcp.controls.control_tests.get_strategy_api", lambda site_id: built
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
    return built


class TestTheRunWritesTheNameItWasGiven:
    async def test_the_default_name_reaches_wdk(self, run_api: _RunFakeAPI) -> None:
        await run_positive_negative_controls(
            _config(), positive_controls=["PF3D7_0100100"]
        )

        assert run_api.created_strategy_names == [DEFAULT_CONTROL_TEST_STRATEGY_NAME]

    async def test_a_caller_supplied_name_reaches_wdk(
        self, run_api: _RunFakeAPI
    ) -> None:
        await run_positive_negative_controls(
            _config(internal_strategy_name="Pathfinder control test"),
            positive_controls=["PF3D7_0100100"],
        )

        assert run_api.created_strategy_names == ["Pathfinder control test"]


class TestOneConfigWritesAndMatches:
    @pytest.mark.parametrize(
        "name", [DEFAULT_CONTROL_TEST_STRATEGY_NAME, "Pathfinder control test"]
    )
    async def test_a_run_s_leftover_is_matched_by_the_same_config(
        self, run_api: _RunFakeAPI, name: str
    ) -> None:
        config = _config(internal_strategy_name=name)
        await run_positive_negative_controls(
            config, positive_controls=["PF3D7_0100100"]
        )
        written = run_api.created_strategy_names[0]
        leftover = _internal(77, written)

        cleanup_api = _FakeStrategyAPI()
        await cleanup_internal_control_test_strategies(cleanup_api, [leftover], config)

        assert cleanup_api.deleted == [77]
