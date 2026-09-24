"""One index per site over its WDK dataset records, and the cards they render.

The cards live beside the index, so a card reads the same whether or not this
process holds its site's catalog.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from veupathdb import JSONObject

from veupathdb_mcp.embeddings.record_manager import (
    IndexEntry,
    SyncReport,
    index_session,
    statement_chunks,
    sync_index,
)
from veupathdb_mcp.embeddings.tables import ExperimentCardRow


def experiment_index_id(site_id: str) -> str:
    """The record manager's id for one site's experiments."""
    return f"experiments:{site_id}"


@dataclass(frozen=True, slots=True)
class ExperimentEntry:
    """One dataset of one site: the text it is found by, and its card as JSON."""

    dataset_id: str
    text: str
    card: JSONObject


async def sync_experiments(
    site_id: str, entries: Sequence[ExperimentEntry]
) -> SyncReport:
    """Make the site's cards and its index hold exactly these datasets.

    An empty list writes nothing, so a report that did not answer keeps the cards.
    """
    if not entries:
        return SyncReport()
    rows = [
        {"site_id": site_id, "dataset_id": entry.dataset_id, "card": entry.card}
        for entry in entries
    ]
    async with index_session() as session:
        for chunk in statement_chunks(rows):
            statement = insert(ExperimentCardRow).values(list(chunk))
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["site_id", "dataset_id"],
                    set_={"card": statement.excluded.card, "updated_at": func.now()},
                ),
            )
        await session.execute(
            delete(ExperimentCardRow).where(
                ExperimentCardRow.site_id == site_id,
                ExperimentCardRow.dataset_id.not_in(
                    [entry.dataset_id for entry in entries]
                ),
            ),
        )
        await session.commit()
    return await sync_index(
        experiment_index_id(site_id),
        [IndexEntry(entry_id=entry.dataset_id, text=entry.text) for entry in entries],
    )


async def read_experiment_cards(
    keys: Sequence[tuple[str, str]],
) -> dict[tuple[str, str], JSONObject]:
    """The stored card of each (site, dataset) pair. A pair with no card is absent."""
    if not keys:
        return {}
    async with index_session() as session:
        rows = await session.execute(
            select(
                ExperimentCardRow.site_id,
                ExperimentCardRow.dataset_id,
                ExperimentCardRow.card,
            ).where(
                tuple_(ExperimentCardRow.site_id, ExperimentCardRow.dataset_id).in_(
                    list(keys)
                ),
            ),
        )
        return {(row.site_id, row.dataset_id): row.card for row in rows}


async def dataset_sites(
    dataset_ids: Sequence[str], site_ids: Sequence[str]
) -> list[tuple[str, str]]:
    """Each (dataset, site) pair whose card the named sites hold, in one read."""
    if not dataset_ids:
        return []
    async with index_session() as session:
        rows = await session.execute(
            select(ExperimentCardRow.dataset_id, ExperimentCardRow.site_id).where(
                ExperimentCardRow.dataset_id.in_(list(dataset_ids)),
                ExperimentCardRow.site_id.in_(list(site_ids)),
            ),
        )
        return [(dataset_id, site_id) for dataset_id, site_id in rows.all()]


async def experiment_organisms(site_ids: Sequence[str]) -> list[tuple[str, str]]:
    """Each (site, organism) pair the named sites' cards carry, once."""
    organism = ExperimentCardRow.card["organism"].astext
    async with index_session() as session:
        rows = await session.execute(
            select(ExperimentCardRow.site_id, organism)
            .where(ExperimentCardRow.site_id.in_(list(site_ids)))
            .distinct(),
        )
        return [(site_id, text) for site_id, text in rows.all()]
