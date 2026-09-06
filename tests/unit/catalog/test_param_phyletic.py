"""The phyletic contract: derive the three values from two species lists, read
the clade tree, and say everywhere that the pattern is never written by hand."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from veupathdb.domain.parameters.phyletic import (
    PhyleticBinding,
    PhyleticNode,
    PhyleticTree,
)
from veupathdb.wdk.phyletic_tree import phyletic_tree_of
from veupathdb.wdk.wdk_parameters import (
    WDKEnumParam,
    WDKParameter,
    WDKStringParam,
)

from veupathdb_mcp.catalog import param_phyletic
from veupathdb_mcp.catalog.param_formatting import _PROFILE_PATTERN_HELP
from veupathdb_mcp.catalog.param_phyletic import (
    LOOKUP_HINT,
    PhyleticNoSelection,
    PhyleticUnresolvedProposal,
    derive_phyletic_overrides,
    is_phyletic_sheet,
)
from veupathdb_mcp.embeddings.embedder import EmbeddingUnavailableError

from .conftest import param_info, vocab, vocab_terms

_TERMS = (
    ("ALL", "Root"),
    ("EUKA", "Eukaryota"),
    ("MAMM", "Mammalia"),
    ("hsap", "Homo sapiens REF"),
    ("mmus", "Mus musculus"),
    ("pfal", "Plasmodium falciparum 3D7"),
)
_INDENTS = (("EUKA", "1"), ("MAMM", "2"), ("hsap", "3"), ("mmus", "3"), ("pfal", "2"))


def _map_param(name: str, pairs: Sequence[tuple[str, str]]) -> WDKEnumParam:
    return WDKEnumParam(
        name=name, type="multi-pick-vocabulary", vocabulary=vocab_terms(*pairs)
    )


def _phyletic_params(
    *,
    terms: Sequence[tuple[str, str]] = _TERMS,
    indents: Sequence[tuple[str, str]] = _INDENTS,
) -> list[WDKParameter]:
    return [
        WDKStringParam(name="profile_pattern", is_visible=False),
        WDKStringParam(name="included_species", allow_empty_value=True),
        WDKStringParam(name="excluded_species", allow_empty_value=True),
        _map_param("phyletic_term_map", terms),
        _map_param("phyletic_indent_map", indents),
    ]


def _ordinary_params() -> list[WDKParameter]:
    return [
        WDKStringParam(name="text_expression"),
        WDKStringParam(name="included_species", allow_empty_value=True),
    ]


class TestABindingIsDerived:
    def test_a_label_and_a_code_bind_the_three_values(self) -> None:
        got = derive_phyletic_overrides(
            _phyletic_params(),
            {
                "included_species": "Plasmodium falciparum 3D7",
                "excluded_species": ["hsap"],
            },
        )

        assert got == PhyleticBinding(
            profile_pattern="%hsap:N%pfal:Y%",
            included_species="pfal",
            excluded_species="hsap",
        )

    def test_a_clade_expands_in_the_pattern_and_stays_a_code_in_the_list(self) -> None:
        got = derive_phyletic_overrides(
            _phyletic_params(),
            {"included_species": "pfal", "excluded_species": "Mammalia"},
        )

        assert got == PhyleticBinding(
            profile_pattern="%hsap:N%mmus:N%pfal:Y%",
            included_species="pfal",
            excluded_species="MAMM",
        )

    def test_one_list_alone_leaves_the_other_empty(self) -> None:
        got = derive_phyletic_overrides(
            _phyletic_params(), {"excluded_species": "hsap"}
        )

        assert got == PhyleticBinding(
            profile_pattern="%hsap:N%", included_species="n/a", excluded_species="hsap"
        )


class TestAnEmptySelection:
    """Two empty lists state no criterion, and the bare wildcard hides that.

    The pattern would bind, the search would run, and it would answer with every
    gene of the chosen organisms as though the phyletic question was asked.
    """

    def test_both_lists_null(self) -> None:
        got = derive_phyletic_overrides(
            _phyletic_params(), {"included_species": None, "excluded_species": None}
        )

        assert got == PhyleticNoSelection()

    def test_both_lists_holding_the_empty_marker(self) -> None:
        got = derive_phyletic_overrides(
            _phyletic_params(), {"included_species": "n/a", "excluded_species": []}
        )

        assert got == PhyleticNoSelection()

    def test_neither_list_was_named(self) -> None:
        """Omitting both lists leaves the hidden pattern to its default, which is
        the same empty criterion the two empty lists state."""
        got = derive_phyletic_overrides(_phyletic_params(), {"organism": ["Pf3D7"]})

        assert got == PhyleticNoSelection()


class TestNothingIsDerived:
    @pytest.mark.parametrize(
        ("proposal", "expected"),
        [
            ({"included_species": "pfal"}, None),
            ({"text_expression": "kinase"}, None),
        ],
    )
    def test_a_search_that_is_not_phyletic_derives_nothing(
        self, proposal: dict[str, str], expected: None
    ) -> None:
        assert derive_phyletic_overrides(_ordinary_params(), proposal) == expected


class TestAnUnresolvedProposal:
    def test_an_unknown_species_names_the_nearest_entries(self) -> None:
        got = derive_phyletic_overrides(
            _phyletic_params(),
            {"included_species": "Plasmodium falciparum", "excluded_species": "hsap"},
        )

        assert isinstance(got, PhyleticUnresolvedProposal)
        assert got.unresolved.included_unknown == ["Plasmodium falciparum"]
        assert "Plasmodium falciparum 3D7" in got.nearest

    def test_the_nearest_list_is_short_enough_to_read(self) -> None:
        got = derive_phyletic_overrides(
            _phyletic_params(), {"excluded_species": "Nosema"}
        )

        assert isinstance(got, PhyleticUnresolvedProposal)
        assert got.unresolved.excluded_unknown == ["Nosema"]
        assert 0 < len(got.nearest) <= 5

    def test_a_code_in_both_lists_is_a_conflict(self) -> None:
        got = derive_phyletic_overrides(
            _phyletic_params(),
            {"included_species": "pfal, hsap", "excluded_species": "hsap"},
        )

        assert isinstance(got, PhyleticUnresolvedProposal)
        assert got.unresolved.conflicts == ["hsap"]


def _sheet_info(name: str, *, visible: bool = True) -> Any:
    return param_info(
        name,
        "string",
        required=False,
        visible=visible,
        leaves=vocab("pfal"),
    )


class TestTheSheetSignature:
    """The two structural maps never reach the sheet, so the other three name it.

    The proposals do not enter the signature: a phyletic search that names no
    list still owes a species selection.
    """

    def test_a_phyletic_sheet(self) -> None:
        assert is_phyletic_sheet(
            [
                _sheet_info("profile_pattern", visible=False),
                _sheet_info("included_species"),
                _sheet_info("excluded_species"),
                _sheet_info("organism"),
            ]
        )

    def test_an_ordinary_sheet(self) -> None:
        assert not is_phyletic_sheet(
            [_sheet_info("included_species"), _sheet_info("organism")]
        )


class TestTheMatchesDescribeTheTree:
    """The lookup reads its clade tree from the search parameters."""

    @pytest.fixture(autouse=True)
    def _tree_order_ranking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rank by tree order, so the test asserts the entries and not the model."""

        async def _tree_order(
            _query: str, candidates: list[tuple[str, str, bool]]
        ) -> list[tuple[str, str, bool]]:
            return candidates

        monkeypatch.setattr(param_phyletic, "_rank_by_semantic_similarity", _tree_order)

    @staticmethod
    async def _matches(params: list[WDKParameter]) -> list[Any]:
        tree = phyletic_tree_of(params)
        assert tree is not None
        return await param_phyletic._match_phyletic_entries(tree, "mammal")

    @staticmethod
    async def _by_code(params: list[WDKParameter]) -> dict[str, Any]:
        return {
            m["code"]: m for m in await TestTheMatchesDescribeTheTree._matches(params)
        }

    async def test_the_synthetic_root_is_not_a_match(self) -> None:
        assert all(m["code"] != "ALL" for m in await self._matches(_phyletic_params()))

    async def test_a_clade_is_reported_as_a_group(self) -> None:
        by_code = await self._by_code(_phyletic_params())

        assert by_code["MAMM"]["leaf"] is False
        assert by_code["EUKA"]["leaf"] is False

    async def test_a_species_is_reported_as_a_leaf(self) -> None:
        by_code = await self._by_code(_phyletic_params())

        assert by_code["hsap"]["leaf"] is True
        assert by_code["pfal"]["leaf"] is True

    async def test_every_code_carries_its_label(self) -> None:
        by_code = await self._by_code(_phyletic_params())

        assert by_code["pfal"]["label"] == "Plasmodium falciparum 3D7"

    async def test_an_empty_tree_matches_nothing(self) -> None:
        assert await self._matches(_phyletic_params(terms=(), indents=())) == []


_UNREACHABLE = EmbeddingUnavailableError(batch_size=1, cause="no route to host")


class _RefusingEmbedder:
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        del texts
        raise _UNREACHABLE

    async def embed_query(self, text: str) -> list[float]:
        del text
        raise _UNREACHABLE


class TestTheRankingSurvivesAnUnreachableEmbeddingApi:
    """An unreachable embedding API costs a ranking, never a call."""

    @pytest.fixture(autouse=True)
    def _refusing_embedder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(param_phyletic, "get_embedder", _RefusingEmbedder)

    async def test_the_ranking_falls_back_to_tree_order(self) -> None:
        candidates = [("hsap", "Homo sapiens", True), ("pfal", "P. falciparum", True)]

        ranked = await param_phyletic._rank_by_semantic_similarity("mammal", candidates)

        assert ranked == candidates

    async def test_the_matches_still_describe_the_tree(self) -> None:
        """The tool answers with the whole tree rather than raising at the model."""
        tree = PhyleticTree(
            roots=[
                PhyleticNode(
                    code="MAMM",
                    label="Mammals",
                    depth=1,
                    children=[PhyleticNode(code="hsap", label="Homo sapiens", depth=2)],
                )
            ]
        )

        matches = await param_phyletic._match_phyletic_entries(tree, "mammal")

        assert [match["code"] for match in matches] == ["MAMM", "hsap"]


class TestEveryPhyleticStringSaysThePatternIsDerived:
    """A string that teaches the pattern grammar invites the model to write one."""

    @staticmethod
    def _normalized(text: str) -> str:
        return " ".join(text.split())

    def test_the_hidden_parameter_help_says_it_is_derived(self) -> None:
        help_text = self._normalized(_PROFILE_PATTERN_HELP)

        assert "It is DERIVED from included_species and excluded_species" in help_text
        assert "never write it" in help_text
        assert "QUANTIFIER" not in help_text

    def test_the_lookup_result_hint_says_it_is_derived(self) -> None:
        hint = self._normalized(LOOKUP_HINT)

        assert "profile_pattern is derived from the two lists; never write it" in hint
        assert "included_species" in hint
        assert "excluded_species" in hint
