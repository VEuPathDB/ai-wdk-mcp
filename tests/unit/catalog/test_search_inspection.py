"""Inspecting one search and reading one parameter's options."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.domain.parameters.values import SinglePickValue
from veupathdb.domain.parameters.wdk_vocab import (
    FAKE_ALL_SENTINEL,
    WDKTreeBoxVocabNode,
    WDKVocabNodeData,
    collect_leaf_terms,
)
from veupathdb.errors import WDKError
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk.wdk_models import WDKSearchResponse

from veupathdb_mcp.catalog import search_inspection, searches
from veupathdb_mcp.catalog.search_inspection import (
    UnknownSearchError,
    VocabNarrowing,
    _prioritized_branches,
    inspect_search,
    read_parameter_options,
)


def _response(name: str) -> WDKSearchResponse:
    return WDKSearchResponse.model_validate(load_recorded(name).json_body())


def _stub_client(monkeypatch: pytest.MonkeyPatch, fixture: str) -> MagicMock:
    response = _response(fixture)
    client = MagicMock()
    client.get_search_details = AsyncMock(return_value=response)
    client.get_search_details_with_params = AsyncMock(return_value=response)
    monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)
    monkeypatch.setattr(search_inspection, "get_wdk_client", lambda _site: client)
    return client


class TestInspectSearch:
    async def test_it_returns_the_overview_and_the_definition_it_came_from(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_client(monkeypatch, "search_genes_by_molecular_weight")

        result = await inspect_search(
            "plasmodb",
            "GenesByMolecularWeight",
            record_type="transcript",
            query="molecular weight of kinases",
        )

        assert result.record_type == "transcript"
        assert result.definition.url_segment == "GenesByMolecularWeight"
        assert [p.name for p in result.definition.parameters or []] == [
            "organism",
            "min_molecular_weight",
            "max_molecular_weight",
        ]
        assert result.overview.search_name == "GenesByMolecularWeight"
        assert result.overview.display_name == "Molecular Weight"
        assert [entry.name for entry in result.overview.required] == [
            "organism",
            "min_molecular_weight",
            "max_molecular_weight",
        ]
        assert result.overview.optional == []

    async def test_it_ranks_without_a_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_client(monkeypatch, "search_genes_by_molecular_weight")

        result = await inspect_search(
            "plasmodb", "GenesByMolecularWeight", record_type="transcript"
        )

        assert [entry.name for entry in result.overview.required] == [
            "organism",
            "min_molecular_weight",
            "max_molecular_weight",
        ]

    async def test_it_resolves_the_record_type_when_none_is_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_client(monkeypatch, "search_genes_by_molecular_weight")

        async def _resolve(_site: str, _search: str, _rt: str | None) -> str:
            return "transcript"

        monkeypatch.setattr(search_inspection, "resolve_search_record_type", _resolve)

        result = await inspect_search("plasmodb", "GenesByMolecularWeight")

        assert result.record_type == "transcript"

    async def test_an_unknown_search_names_the_valid_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = MagicMock()
        client.get_search_details = AsyncMock(
            side_effect=WDKError("Resource 'search: Nope' does not exist.", status=404)
        )
        monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)

        async def _valid(_site: str, _rt: str) -> list[Any]:
            return [_raw("GenesByMolecularWeight"), _raw("GenesByLocation")]

        monkeypatch.setattr(search_inspection, "get_raw_searches", _valid)

        with pytest.raises(UnknownSearchError) as excinfo:
            await inspect_search(
                "plasmodb", "GenesByMolecularWeigh", record_type="transcript"
            )

        guidance = excinfo.value.guidance
        assert "GenesByMolecularWeigh" in guidance
        assert "GenesByMolecularWeight" in guidance
        assert "Valid search values" in guidance

    async def test_a_non_404_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MagicMock()
        client.get_search_details = AsyncMock(
            side_effect=WDKError("upstream 502", status=502)
        )
        monkeypatch.setattr(searches, "get_wdk_client", lambda _site: client)

        with pytest.raises(WDKError):
            await inspect_search("plasmodb", "Whatever", record_type="transcript")


def _raw(name: str) -> Any:
    raw = MagicMock()
    raw.url_segment = name
    return raw


class TestReadParameterOptions:
    async def test_it_formats_one_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_client(monkeypatch, "search_genes_by_location")

        result = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "organismSinglePick",
            record_type="transcript",
        )

        assert result.kind == "parameter_info"
        assert result.name == "organismSinglePick"
        assert result.controls_vocab_of == ["chromosomeOptional"]
        assert result.allowed_values

    async def test_a_query_narrows_the_vocabulary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_client(monkeypatch, "search_genes_by_location")

        whole = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "organismSinglePick",
            record_type="transcript",
        )
        narrowed = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "organismSinglePick",
            record_type="transcript",
            narrowing=VocabNarrowing(query="falciparum"),
        )

        assert whole.kind == "parameter_info"
        assert narrowed.kind == "parameter_info"
        assert narrowed.allowed_values is not None
        assert whole.allowed_values is not None
        assert 0 < len(narrowed.allowed_values) < len(whole.allowed_values)
        assert all(
            "falciparum" in option.value.lower()
            or "falciparum" in option.display.lower()
            for option in narrowed.allowed_values
        )

    async def test_a_query_narrows_a_tree_vocabulary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A tree keeps the branches that match and the path down to them."""
        _stub_client(monkeypatch, "search_genes_by_molecular_weight")

        whole = await read_parameter_options(
            "plasmodb",
            "GenesByMolecularWeight",
            "organism",
            record_type="transcript",
        )
        narrowed = await read_parameter_options(
            "plasmodb",
            "GenesByMolecularWeight",
            "organism",
            record_type="transcript",
            narrowing=VocabNarrowing(query="falciparum"),
        )

        assert whole.kind == "parameter_info"
        assert narrowed.kind == "parameter_info"
        assert len(whole.vocab_leaves) == 90
        assert len(narrowed.vocab_leaves) == 25
        values = [option.value for option in narrowed.vocab_leaves]
        assert "Plasmodium falciparum 3D7" in values
        assert "Plasmodium berghei ANKA" not in values
        assert "Plasmodium falciparum 3D7" in narrowed.allowed_values_tree
        assert "Plasmodium berghei ANKA" not in narrowed.allowed_values_tree
        assert "Plasmodium berghei ANKA" in whole.allowed_values_tree

    async def test_organism_hints_float_the_matching_branches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The tree is capped, so the investigation's organism is rendered first."""
        _stub_client(monkeypatch, "search_genes_by_molecular_weight")

        whole = await read_parameter_options(
            "plasmodb",
            "GenesByMolecularWeight",
            "organism",
            record_type="transcript",
        )
        hinted = await read_parameter_options(
            "plasmodb",
            "GenesByMolecularWeight",
            "organism",
            record_type="transcript",
            narrowing=VocabNarrowing(organism_hints=["Plasmodium falciparum"]),
        )

        assert whole.kind == "parameter_info"
        assert hinted.kind == "parameter_info"
        assert len(hinted.vocab_leaves) == len(whole.vocab_leaves) == 90
        unbiased_tree = whole.allowed_values_tree
        hinted_tree = hinted.allowed_values_tree
        assert unbiased_tree is not None
        assert hinted_tree is not None
        assert "Plasmodium falciparum 3D7" in hinted_tree

        def _first_falciparum(tree: str) -> int:
            return next(
                index
                for index, line in enumerate(tree.splitlines())
                if "Plasmodium falciparum 3D7" in line
            )

        hinted_at = _first_falciparum(hinted_tree)
        assert hinted_at < _first_falciparum(unbiased_tree)
        assert hinted_at < 5

    async def test_a_query_reads_the_terms_and_not_their_repr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A list entry is matched on its term and its label, nothing else."""
        _stub_client(monkeypatch, "search_genes_by_location")

        whole = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "organismSinglePick",
            record_type="transcript",
        )
        result = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "organismSinglePick",
            record_type="transcript",
            narrowing=VocabNarrowing(query="root="),
        )

        assert whole.kind == "parameter_info"
        assert whole.allowed_values is not None
        assert len(whole.allowed_values) == 48
        assert result.kind == "parameter_info"
        assert result.allowed_values is None
        assert result.vocab_leaves == []

    async def test_a_dependent_parameter_asks_for_its_parent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_client(monkeypatch, "search_genes_by_location")

        result = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "chromosomeOptional",
            record_type="transcript",
        )

        assert result.kind == "parent_context_required"
        assert result.parent_parameter_ids == ["organismSinglePick"]

    async def test_context_travels_by_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _stub_client(monkeypatch, "search_genes_by_location")

        result = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "chromosomeOptional",
            record_type="transcript",
            context_values={"organismSinglePick": "Plasmodium falciparum 3D7"},
        )

        assert result.kind == "parameter_info"
        assert client.get_search_details_with_params.await_count == 1
        context = client.get_search_details_with_params.await_args.kwargs["context"]
        assert context["organismSinglePick"] == "Plasmodium falciparum 3D7"

    async def test_it_accepts_already_typed_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _stub_client(monkeypatch, "search_genes_by_location")

        result = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "chromosomeOptional",
            record_type="transcript",
            context_values={
                "organismSinglePick": SinglePickValue(value="Plasmodium falciparum 3D7")
            },
        )

        assert result.kind == "parameter_info"
        context = client.get_search_details_with_params.await_args.kwargs["context"]
        assert context["organismSinglePick"] == "Plasmodium falciparum 3D7"

    async def test_an_unknown_parameter_names_the_valid_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_client(monkeypatch, "search_genes_by_location")

        result = await read_parameter_options(
            "plasmodb",
            "GenesByLocation",
            "organism_single_pick",
            record_type="transcript",
        )

        assert result.kind == "parameter_not_on_search"
        assert result.suggestions == ["organismSinglePick"]
        assert result.valid_parameter_ids == [
            "chromosomeOptional",
            "end_point",
            "organismSinglePick",
            "sequenceId",
            "start_point",
        ]


def _node(term: str, *children: WDKTreeBoxVocabNode) -> WDKTreeBoxVocabNode:
    return WDKTreeBoxVocabNode(
        data=WDKVocabNodeData(term=term, display=term),
        children=list(children),
    )


def _two_genus_tree() -> WDKTreeBoxVocabNode:
    return _node(
        FAKE_ALL_SENTINEL,
        _node("Anopheles", _node("Anopheles gambiae PEST")),
        _node("Plasmodium", _node("Plasmodium falciparum 3D7")),
    )


class TestPrioritizedBranches:
    def test_a_hint_floats_the_branch_that_reaches_it(self) -> None:
        ordered = _prioritized_branches(_two_genus_tree(), ["falciparum"])

        assert [child.data.term for child in ordered.children] == [
            "Plasmodium",
            "Anopheles",
        ]

    def test_nothing_is_dropped(self) -> None:
        ordered = _prioritized_branches(_two_genus_tree(), ["falciparum"])

        assert sorted(collect_leaf_terms(ordered)) == [
            "Anopheles gambiae PEST",
            "Plasmodium falciparum 3D7",
        ]

    def test_no_hint_keeps_the_wdk_order(self) -> None:
        ordered = _prioritized_branches(_two_genus_tree(), [])

        assert [child.data.term for child in ordered.children] == [
            "Anopheles",
            "Plasmodium",
        ]

    def test_a_hint_that_matches_nothing_keeps_the_wdk_order(self) -> None:
        ordered = _prioritized_branches(_two_genus_tree(), ["Toxoplasma"])

        assert [child.data.term for child in ordered.children] == [
            "Anopheles",
            "Plasmodium",
        ]
