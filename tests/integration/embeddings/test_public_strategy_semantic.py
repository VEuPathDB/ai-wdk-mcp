"""Public strategies are synced into their site's index, then ranked from it."""

from __future__ import annotations

import pytest
from veupathdb.json_types import JSONObject
from veupathdb.wdk.wdk_models import WDKStrategySummary

from veupathdb_mcp.catalog import public_strategy_search
from veupathdb_mcp.catalog.public_strategy_search import (
    public_strategy_index_id,
    rank_public_strategies_semantic,
)
from veupathdb_mcp.embeddings.embedder import EmbeddingUnavailableError
from veupathdb_mcp.embeddings.fake import FakeEmbedder
from veupathdb_mcp.embeddings.record_manager import IndexHit, index_size

pytestmark = pytest.mark.asyncio


def _strat(sid: int, name: str, desc: str = "") -> WDKStrategySummary:
    return WDKStrategySummary(
        strategy_id=sid, name=name, root_step_id=sid, description=desc
    )


@pytest.fixture
def db(
    patch_app_db_engine: None,
    embedding_index_cleaner: None,
) -> None:
    del patch_app_db_engine, embedding_index_cleaner


async def test_the_first_call_syncs_the_site_index(db: None) -> None:
    del db
    strategies = [_strat(1, "Vaccine antigens"), _strat(2, "Drug targets")]
    await rank_public_strategies_semantic(
        strategies, "immunization targets", site_id="plasmodb", min_score=-1.0
    )
    assert await index_size(public_strategy_index_id("plasmodb")) == 2


async def test_a_second_call_over_the_same_list_embeds_nothing(
    db: None,
    fake_embedder: FakeEmbedder,
) -> None:
    del db
    strategies = [_strat(1, "Vaccine antigens"), _strat(2, "Drug targets")]
    await rank_public_strategies_semantic(
        strategies, "q", site_id="plasmodb", min_score=-1.0
    )
    fake_embedder.calls.clear()
    await rank_public_strategies_semantic(
        strategies, "q", site_id="plasmodb", min_score=-1.0
    )
    # Only the query is embedded; the two documents are reused.
    assert fake_embedder.calls == [["q"]]


async def test_ranking_follows_the_index_order(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del db
    strategies = [_strat(1, "A"), _strat(2, "B"), _strat(3, "C")]

    async def ranked(index_id: str, query: str, top_k: int) -> list[IndexHit]:
        del index_id, query, top_k
        return [
            IndexHit(entry_id="1", similarity=0.9),
            IndexHit(entry_id="3", similarity=0.6),
            IndexHit(entry_id="2", similarity=0.1),
        ]

    monkeypatch.setattr(public_strategy_search, "search_index", ranked)
    out = await rank_public_strategies_semantic(
        strategies, "q", site_id="plasmodb", limit=3, min_score=-1.0
    )
    assert [r["name"] for r in out] == ["A", "C", "B"]


async def test_a_hit_below_the_threshold_is_dropped(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del db
    strategies = [_strat(1, "A"), _strat(2, "B")]

    async def ranked(index_id: str, query: str, top_k: int) -> list[IndexHit]:
        del index_id, query, top_k
        return [
            IndexHit(entry_id="1", similarity=0.9),
            IndexHit(entry_id="2", similarity=0.0),
        ]

    monkeypatch.setattr(public_strategy_search, "search_index", ranked)
    out = await rank_public_strategies_semantic(
        strategies, "q", site_id="plasmodb", limit=3, min_score=0.4
    )
    assert [r["name"] for r in out] == ["A"]


async def test_empty_inputs_reach_no_index(db: None) -> None:
    del db
    empty: list[WDKStrategySummary] = []
    assert await rank_public_strategies_semantic(empty, "q", site_id="plasmodb") == []
    assert (
        await rank_public_strategies_semantic(
            [_strat(1, "A")], "   ", site_id="plasmodb"
        )
        == []
    )
    assert await index_size(public_strategy_index_id("plasmodb")) == 0


async def test_an_unreachable_api_raises_for_the_caller_to_fall_back(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    del db

    async def refuse(index_id: str, query: str, top_k: int) -> list[IndexHit]:
        del index_id, query, top_k
        raise EmbeddingUnavailableError(batch_size=1, cause="no route to host")

    monkeypatch.setattr(public_strategy_search, "search_index", refuse)
    with pytest.raises(EmbeddingUnavailableError):
        await rank_public_strategies_semantic([_strat(1, "A")], "q", site_id="plasmodb")


async def test_the_lexical_fallback_still_ranks(db: None) -> None:
    del db
    out: list[JSONObject] = public_strategy_search.rank_public_strategies(
        [_strat(1, "Vaccine antigens"), _strat(2, "Drug targets")],
        query="vaccine",
        limit=3,
    )
    assert [r["name"] for r in out] == ["Vaccine antigens"]
