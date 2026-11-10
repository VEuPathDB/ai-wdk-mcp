"""A question about genomes finds the organism columns that answer it."""

from __future__ import annotations

import pytest
from tests._support.record_columns_site import (
    recorded_record_type,
    serve_recorded_records,
)

from veupathdb_mcp.embeddings.column_index import sync_record_columns
from veupathdb_mcp.records import rank_record_columns

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def indexed(
    patch_app_db_engine: None,
    embedding_index_cleaner: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del patch_app_db_engine, embedding_index_cleaner
    serve_recorded_records(monkeypatch)
    await sync_record_columns(
        "veupathdb", [recorded_record_type("veupathdb_organism_record_type.json")]
    )


async def test_busco_completeness_finds_the_busco_columns(indexed: None) -> None:
    del indexed

    matches = await rank_record_columns(
        "veupathdb", "BUSCO completeness score of the genome assembly", top_k=3
    )

    assert [(m.record_type, m.kind, m.name) for m in matches][:2] == [
        ("organism", "column", "busco_genome"),
        ("organism", "column", "busco_protein"),
    ]
    assert matches[0].display_name == "BUSCO Genomic"


async def test_a_question_sharing_no_words_finds_nothing(indexed: None) -> None:
    del indexed

    assert await rank_record_columns("veupathdb", "zzzz qqqq", top_k=3) == []


async def test_another_site_has_its_own_index(indexed: None) -> None:
    del indexed

    assert await rank_record_columns("orthomcl", "BUSCO completeness", top_k=3) == []
