"""Semantic index over EDA study names and descriptions."""

from __future__ import annotations

from collections.abc import Sequence

from veupathdb.eda.models import EdaStudyOverview

from veupathdb_mcp.embeddings.record_manager import (
    IndexEntry,
    IndexHit,
    SyncReport,
    index_size,
    search_index,
    sync_index,
)
from veupathdb_mcp.embeddings.semantic_index import strip_markup

# Characters of a description the index reads. A text costs by the window the
# model reads over it, not by the description an author wrote.
DESCRIPTION_LIMIT = 2000

# The EDA service answers with the portal's catalog, the same on every site,
# so one index serves them all.
STUDY_INDEX_ID = "eda-studies"


def study_enriched_text(study: EdaStudyOverview) -> str:
    """The text a study is indexed by: its names first, then its description."""
    parts = [study.display_name]
    short = study.short_display_name or ""
    if short and short != study.display_name:
        parts.append(short)
    if study.description:
        parts.append(strip_markup(study.description).strip()[:DESCRIPTION_LIMIT])
    return " ".join(p.strip() for p in parts if p and p.strip()).strip()


async def sync_study_index(studies: Sequence[EdaStudyOverview]) -> SyncReport:
    """Make the study index hold exactly these studies."""
    return await sync_index(
        STUDY_INDEX_ID,
        [
            IndexEntry(entry_id=study.dataset_id, text=study_enriched_text(study))
            for study in studies
        ],
    )


async def search_study_index(query: str, top_k: int) -> list[IndexHit]:
    """The studies nearest the query, best first."""
    return await search_index(STUDY_INDEX_ID, query, top_k)


async def study_index_is_built() -> bool:
    """Whether the study index holds any member at all."""
    return await index_size(STUDY_INDEX_ID) > 0
