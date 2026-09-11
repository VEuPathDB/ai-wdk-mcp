"""A step that holds exactly the gene ids a set stores, and how it is keyed."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.domain.parameters import InputDatasetValue, ParamValue
from veupathdb.errors import WDKLoginRequiredError
from veupathdb.wdk import NewStepSpec, WDKIdentifier, WDKStepTree

from veupathdb_mcp.wdk import gene_set_steps
from veupathdb_mcp.wdk.gene_set_steps import (
    DEFAULT_GENE_SET_STRATEGY_NAME,
    frozen_step_cache_key,
    frozen_step_id,
)

GENE_A = "PF3D7_0100100"
GENE_B = "PF3D7_0200200"

ALICE = "bearer-alice"
BOB = "bearer-bob"


@contextmanager
def _acting_as(token: str) -> Iterator[None]:
    """Run the block under the WDK token one account signed in with."""
    reset = veupathdb_auth_token_ctx.set(token)
    try:
        yield
    finally:
        veupathdb_auth_token_ctx.reset(reset)


class _FakeStrategyAPI:
    def __init__(self) -> None:
        self.created_strategy_names: list[str] = []
        self.step_specs: list[NewStepSpec] = []
        self.step_trees: list[WDKStepTree] = []
        self._next_id = 500

    async def create_step(
        self, spec: NewStepSpec, record_type: str, user_id: str | None = None
    ) -> WDKIdentifier:
        self.step_specs.append(spec)
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
        self.step_trees.append(step_tree)
        return WDKIdentifier(id=9000)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeStrategyAPI]:
    gene_set_steps._FROZEN_STEPS.clear()
    built = _FakeStrategyAPI()
    monkeypatch.setattr(
        "veupathdb_mcp.wdk.gene_set_steps.get_strategy_api", lambda site_id: built
    )

    async def _params(
        site_id: str, gene_ids: list[str]
    ) -> tuple[str, dict[str, ParamValue], str]:
        return (
            "GeneByLocusTag",
            {"ds_gene_ids": InputDatasetValue(dataset_id="ds-1")},
            "transcript",
        )

    monkeypatch.setattr(
        "veupathdb_mcp.wdk.gene_set_steps.build_enrichment_params_from_gene_ids",
        _params,
    )
    with _acting_as(ALICE):
        yield built


class TestTheKeyIsTheAccountAndTheMembership:
    def test_the_same_ids_key_the_same_step(self) -> None:
        assert frozen_step_cache_key(ALICE, "plasmodb", [GENE_A, GENE_B]) == (
            frozen_step_cache_key(ALICE, "plasmodb", [GENE_A, GENE_B])
        )

    def test_order_does_not_make_a_new_step(self) -> None:
        assert frozen_step_cache_key(ALICE, "plasmodb", [GENE_A, GENE_B]) == (
            frozen_step_cache_key(ALICE, "plasmodb", [GENE_B, GENE_A])
        )

    def test_a_different_membership_keys_a_different_step(self) -> None:
        assert frozen_step_cache_key(ALICE, "plasmodb", [GENE_A]) != (
            frozen_step_cache_key(ALICE, "plasmodb", [GENE_A, GENE_B])
        )

    def test_the_same_ids_on_another_site_key_another_step(self) -> None:
        assert frozen_step_cache_key(ALICE, "plasmodb", [GENE_A]) != (
            frozen_step_cache_key(ALICE, "toxodb", [GENE_A])
        )

    def test_the_same_ids_in_another_account_key_another_step(self) -> None:
        assert frozen_step_cache_key(ALICE, "plasmodb", [GENE_A]) != (
            frozen_step_cache_key(BOB, "plasmodb", [GENE_A])
        )


class TestTheStepIsHeldByAnInternalStrategy:
    async def test_an_empty_set_creates_nothing(self, api: _FakeStrategyAPI) -> None:
        assert await frozen_step_id("plasmodb", [], "transcript") is None
        assert api.step_specs == []

    async def test_the_step_holds_the_stored_ids(self, api: _FakeStrategyAPI) -> None:
        step_id = await frozen_step_id("plasmodb", [GENE_A, GENE_B], "transcript")

        assert step_id == 501
        assert api.step_specs[0].search_name == "GeneByLocusTag"
        assert api.step_trees == [WDKStepTree(step_id=501)]

    async def test_the_caller_names_the_internal_strategy(
        self, api: _FakeStrategyAPI
    ) -> None:
        await frozen_step_id(
            "plasmodb",
            [GENE_A],
            "transcript",
            strategy_name="Pathfinder gene set",
        )

        assert api.created_strategy_names == ["Pathfinder gene set"]

    async def test_the_default_name_names_no_product(
        self, api: _FakeStrategyAPI
    ) -> None:
        await frozen_step_id("plasmodb", [GENE_A], "transcript")

        assert api.created_strategy_names == [DEFAULT_GENE_SET_STRATEGY_NAME]
        assert "pathfinder" not in DEFAULT_GENE_SET_STRATEGY_NAME.lower()

    async def test_the_same_caller_twice_reuses_the_step(
        self, api: _FakeStrategyAPI
    ) -> None:
        first = await frozen_step_id("plasmodb", [GENE_A, GENE_B], "transcript")
        second = await frozen_step_id("plasmodb", [GENE_B, GENE_A], "transcript")

        assert first == second
        assert len(api.step_specs) == 1

    async def test_another_account_gets_a_step_of_its_own(
        self, api: _FakeStrategyAPI
    ) -> None:
        """A step id names a step in one account, so the key names the account."""
        first = await frozen_step_id("plasmodb", [GENE_A, GENE_B], "transcript")
        with _acting_as(BOB):
            second = await frozen_step_id("plasmodb", [GENE_A, GENE_B], "transcript")

        assert first != second
        assert len(api.step_specs) == 2

    async def test_a_call_that_names_no_account_is_refused(
        self, api: _FakeStrategyAPI
    ) -> None:
        reset = veupathdb_auth_token_ctx.set(None)
        try:
            with pytest.raises(WDKLoginRequiredError):
                await frozen_step_id("plasmodb", [GENE_A], "transcript")
        finally:
            veupathdb_auth_token_ctx.reset(reset)

        assert api.step_specs == []
