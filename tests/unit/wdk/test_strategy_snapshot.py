"""The AST a WDK strategy converts into, and the values a sync canonicalizes.

The fixture is the shape WDK returns for a saved strategy: a combine over a
transform, plus a combine WDK marks as an expanded saved sub-strategy.
"""

from __future__ import annotations

import json

import pytest
from veupathdb.domain.parameters.values import MultiPickValue
from veupathdb.domain.strategy.ops import CombineOp
from veupathdb.domain.strategy.tree import walk
from veupathdb.errors import DataParsingError
from veupathdb.wdk.wdk_models import (
    WDKSearchConfig,
    WDKSearchResponse,
    WDKStep,
    WDKStepTree,
    WDKStrategyDetails,
)

from veupathdb_mcp.wdk import (
    build_snapshot_from_wdk,
    canonicalize_synced_parameters,
    strategy_snapshot,
)

_BOOLEAN = "boolean_question_TranscriptRecordClasses_TranscriptRecordClass"


def _step(
    step_id: int,
    search_name: str,
    parameters: dict[str, str] | None = None,
    **extra: object,
) -> WDKStep:
    return WDKStep.model_validate(
        {
            "id": step_id,
            "search_name": search_name,
            "search_config": WDKSearchConfig(parameters=parameters or {}),
            "custom_name": f"name-{step_id}",
            **extra,
        }
    )


def _tree() -> WDKStepTree:
    return WDKStepTree(
        step_id=40,
        primary_input=WDKStepTree(step_id=30, primary_input=WDKStepTree(step_id=10)),
        secondary_input=WDKStepTree(step_id=20),
    )


def _details() -> WDKStrategyDetails:
    return WDKStrategyDetails(
        strategy_id=7,
        name="kinases",
        root_step_id=40,
        record_class_name="transcript",
        step_tree=_tree(),
        steps={
            "10": _step(
                10, "GenesByText", {"text_expression": "kinase"}, estimated_size=5
            ),
            "20": _step(20, "GenesByTaxon", strategy_id=99, estimated_size=7),
            "30": _step(30, "GenesByOrthologs", estimated_size=3),
            "40": _step(
                40,
                _BOOLEAN,
                {"bq_operator": "INTERSECT"},
                expanded=True,
                expanded_name="saved-1",
                estimated_size=2,
            ),
        },
    )


class TestTheAstBuiltFromWdk:
    def test_the_root_is_a_combine_over_the_transform_and_the_leaf(self) -> None:
        ast, _ = build_snapshot_from_wdk(_details())

        assert ast.root.id == "40"
        assert ast.root.search_name == _BOOLEAN
        assert ast.root.operator is CombineOp.INTERSECT
        assert ast.root.primary_input is not None
        assert ast.root.primary_input.id == "30"
        assert ast.root.secondary_input is not None
        assert ast.root.secondary_input.id == "20"

    def test_the_transform_keeps_its_own_input(self) -> None:
        ast, _ = build_snapshot_from_wdk(_details())

        transform = ast.root.primary_input
        assert transform is not None
        assert transform.search_name == "GenesByOrthologs"
        assert transform.primary_input is not None
        assert transform.primary_input.id == "10"

    def test_an_expanded_combine_names_the_saved_strategy_on_its_secondary(
        self,
    ) -> None:
        ast, _ = build_snapshot_from_wdk(_details())

        assert ast.root.expanded_strategy_id == 99
        assert ast.root.expanded_name == "saved-1"

    def test_only_leaf_and_transform_wire_parameters_go_to_the_sidecar(self) -> None:
        _, wire = build_snapshot_from_wdk(_details())

        assert wire == {
            "10": {"text_expression": "kinase"},
            "20": {},
            "30": {},
        }

    def test_counts_and_wdk_ids_come_back_keyed_by_step_id(self) -> None:
        ast, _ = build_snapshot_from_wdk(_details())

        assert ast.wdk_step_ids == {"10": 10, "20": 20, "30": 30, "40": 40}
        assert ast.step_counts == {"10": 5, "20": 7, "30": 3, "40": 2}

    def test_a_strategy_without_a_record_class_is_refused(self) -> None:
        details = _details().model_copy(update={"record_class_name": " "})

        with pytest.raises(DataParsingError):
            build_snapshot_from_wdk(details)


class _FakeStrategyAPI:
    """Carries the client attribute the spec read names, and nothing else."""

    client = object()


def _organism_search(vocabulary: list[str]) -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(
        {
            "searchData": {
                "urlSegment": "GenesByTaxon",
                "displayName": "Genes by taxon",
                "parameters": [
                    {
                        "name": "organism",
                        "displayName": "Organism",
                        "type": "multi-pick-vocabulary",
                        "vocabulary": [[value, value, None] for value in vocabulary],
                    }
                ],
            },
            "validation": {"level": "SEMANTIC", "isValid": True},
        }
    )


async def test_a_wire_value_is_decoded_against_the_searchs_own_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sidecar's strings become typed values, keyed by the step that sent them."""
    organism = "Plasmodium falciparum 3D7"

    async def _read(
        client: object,
        record_type: str,
        search_name: str,
        context: dict[str, str],
    ) -> WDKSearchResponse:
        del client, record_type, search_name, context
        return _organism_search([organism])

    monkeypatch.setattr(strategy_snapshot, "get_search_params_under_context", _read)

    details = _details().model_copy(
        update={
            "steps": {
                **_details().steps,
                "20": _step(20, "GenesByTaxon", {"organism": json.dumps([organism])}),
            }
        }
    )
    ast, wire = build_snapshot_from_wdk(details)
    await canonicalize_synced_parameters(ast, _FakeStrategyAPI(), wire)

    leaf = next(step for step in walk(ast.root) if step.search_name == "GenesByTaxon")
    assert leaf.parameters == {"organism": MultiPickValue(values=[organism])}


async def test_a_step_whose_spec_is_unreachable_keeps_its_empty_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unreadable(
        client: object,
        record_type: str,
        search_name: str,
        context: dict[str, str],
    ) -> WDKSearchResponse:
        del client, record_type, search_name, context
        msg = "search is unreachable"
        raise DataParsingError(msg)

    monkeypatch.setattr(
        strategy_snapshot, "get_search_params_under_context", _unreadable
    )

    ast, wire = build_snapshot_from_wdk(_details())
    await canonicalize_synced_parameters(ast, _FakeStrategyAPI(), wire)

    leaf = next(step for step in walk(ast.root) if step.search_name == "GenesByText")
    assert leaf.parameters == {}
