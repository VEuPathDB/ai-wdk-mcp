"""The semantic bonus boosts a keyword candidate on a cosine scale.

The boost is calibrated against the lexical scores measured on the plasmodb
snapshot, so a cosine of 0.7 is worth what a strong lexical match is worth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest
from veupathdb.wdk.wdk_models import WDKSearch

from veupathdb_mcp.catalog import semantic_matching
from veupathdb_mcp.catalog.discovery_service import DiscoveryService
from veupathdb_mcp.catalog.models import SearchMatch
from veupathdb_mcp.embeddings.embedder import EmbeddingUnavailableError
from veupathdb_mcp.embeddings.semantic_index import SemanticSearchIndex

SemanticHit = tuple[str, str, float]

# The top lexical score of five research queries against the 515 plasmodb
# searches, measured 2026-08-29: 45.3, 106.9, 44.7, 49.2, 60.4.
STRONG_LEXICAL_SCORE = 49.2


@dataclass
class _StubIndex(SemanticSearchIndex):
    """An index that answers from a fixed list and records that it was read."""

    hits: list[SemanticHit] = field(default_factory=list)
    reads: int = 0
    refuse: bool = False

    async def query(self, query_text: str, top_k: int = 20) -> list[SemanticHit]:
        del query_text, top_k
        self.reads += 1
        if self.refuse:
            raise EmbeddingUnavailableError(batch_size=1, cause="no route to host")
        return list(self.hits)


class _FakeCatalog:
    def __init__(self, index: SemanticSearchIndex) -> None:
        self._index = index

    def get_semantic_index(self) -> SemanticSearchIndex:
        return self._index

    def find_search(self, record_type: str, search_name: str) -> None:
        """No catalog entry, so an injected search is skipped."""
        del record_type, search_name


class _ResolvingCatalog(_FakeCatalog):
    """A catalog that owns the searches, so an injected hit becomes a candidate."""

    def find_search(self, record_type: str, search_name: str) -> WDKSearch:
        del record_type
        return WDKSearch(url_segment=search_name, display_name=search_name)


class _FakeDiscovery:
    def __init__(self, catalog: _FakeCatalog) -> None:
        self._catalog = catalog

    async def get_catalog(self, site_id: str) -> _FakeCatalog:
        del site_id
        return self._catalog


def _match(name: str) -> SearchMatch:
    return SearchMatch(
        name=name, display_name=name, description="", record_type="transcript"
    )


def _discovery(index: SemanticSearchIndex) -> DiscoveryService:
    return cast("DiscoveryService", _FakeDiscovery(_FakeCatalog(index)))


def _resolving_discovery(index: SemanticSearchIndex) -> DiscoveryService:
    return cast("DiscoveryService", _FakeDiscovery(_ResolvingCatalog(index)))


def test_a_cosine_of_seven_tenths_is_worth_a_strong_lexical_match() -> None:
    bonus = semantic_matching._SEMANTIC_BOOST * 0.7
    assert abs(bonus - STRONG_LEXICAL_SCORE) / STRONG_LEXICAL_SCORE < 0.10


def test_the_injection_floor_is_a_cosine() -> None:
    assert semantic_matching._MIN_SEMANTIC_SIM == 0.35


@pytest.mark.asyncio
async def test_a_similar_search_is_boosted_by_its_cosine() -> None:
    index = _StubIndex(hits=[("GenesByGoTerm", "transcript", 0.5)])
    scored = [(1.0, _match("GenesByGoTerm")), (2.0, _match("GenesByText"))]

    await semantic_matching.apply_semantic_bonus(
        scored, _discovery(index), "plasmodb", "kinase", ["transcript"]
    )

    assert scored[0][0] == pytest.approx(1.0 + semantic_matching._SEMANTIC_BOOST * 0.5)
    assert scored[1][0] == pytest.approx(2.0), "an unmatched search keeps its score"


@pytest.mark.asyncio
async def test_a_hit_from_another_record_type_is_not_boosted() -> None:
    index = _StubIndex(hits=[("GenesByGoTerm", "genomic-sequence", 0.9)])
    scored = [(1.0, _match("GenesByGoTerm"))]

    await semantic_matching.apply_semantic_bonus(
        scored, _discovery(index), "plasmodb", "kinase", ["transcript"]
    )

    assert scored[0][0] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_an_empty_query_reads_no_index() -> None:
    index = _StubIndex(hits=[("GenesByGoTerm", "transcript", 0.9)])
    scored = [(1.0, _match("GenesByGoTerm"))]

    await semantic_matching.apply_semantic_bonus(
        scored, _discovery(index), "plasmodb", "", ["transcript"]
    )

    assert index.reads == 0
    assert scored[0][0] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_an_unreachable_embedding_api_leaves_the_lexical_ranking() -> None:
    index = _StubIndex(hits=[("GenesByGoTerm", "transcript", 0.9)], refuse=True)
    scored = [(1.0, _match("GenesByGoTerm")), (2.0, _match("GenesByText"))]

    await semantic_matching.apply_semantic_bonus(
        scored, _discovery(index), "plasmodb", "kinase", ["transcript"]
    )

    assert index.reads == 1
    assert [score for score, _ in scored] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_a_hit_under_the_floor_is_not_injected() -> None:
    """The floor is what keeps a weak cosine out of the candidate list."""
    index = _StubIndex(hits=[("GenesByGoTerm", "transcript", 0.2)])
    scored = [(1.0, _match("GenesByText"))]

    await semantic_matching.apply_semantic_bonus(
        scored, _resolving_discovery(index), "plasmodb", "kinase", ["transcript"]
    )

    assert [entry.name for _, entry in scored] == ["GenesByText"]


@pytest.mark.asyncio
async def test_a_hit_over_the_floor_is_injected_with_its_bonus() -> None:
    index = _StubIndex(hits=[("GenesByGoTerm", "transcript", 0.5)])
    scored = [(1.0, _match("GenesByText"))]

    await semantic_matching.apply_semantic_bonus(
        scored, _resolving_discovery(index), "plasmodb", "kinase", ["transcript"]
    )

    assert [entry.name for _, entry in scored] == ["GenesByText", "GenesByGoTerm"]
    assert scored[1][0] == pytest.approx(semantic_matching._SEMANTIC_BOOST * 0.5)
    assert scored[1][0] == pytest.approx(35.0)
