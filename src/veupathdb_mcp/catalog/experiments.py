"""Experiments on the other sites a deployment serves, each labelled with its site.

A host shows them beside its own site's searches and binds none of them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from pydantic import ConfigDict
from veupathdb.model import CamelModel
from veupathdb.wdk import get_site_router

from veupathdb_mcp.catalog.experiment_card import ORGANISM_SEPARATOR, ExperimentCard
from veupathdb_mcp.catalog.semantic_matching import _MIN_SEMANTIC_SIM
from veupathdb_mcp.embeddings.experiment_index import (
    dataset_sites,
    experiment_index_id,
    experiment_organisms,
    read_experiment_cards,
)
from veupathdb_mcp.embeddings.record_manager import search_indexes


class ExperimentMatch(CamelModel):
    """Another site's experiment, and its cosine against the query."""

    model_config = ConfigDict(frozen=True)

    card: ExperimentCard
    similarity: float


class UnknownExperimentError(LookupError):
    """The site holds no card for the dataset."""

    def __init__(self, site_id: str, dataset_id: str) -> None:
        self.site_id = site_id
        self.dataset_id = dataset_id
        super().__init__(f"{site_id} holds no dataset_id {dataset_id!r}")


def _component_site_ids() -> list[str]:
    """Every site this deployment serves except the portal."""
    return [site.id for site in get_site_router().list_sites() if not site.is_portal]


async def rank_experiments_elsewhere(
    site_id: str, query: str, *, limit: int = 3
) -> list[ExperimentMatch]:
    """The best experiment of each other component site, the best sites first.

    A site whose best cosine is under the semantic floor gives none. The portal
    already spans every organism, so it has no elsewhere.
    """
    if get_site_router().get_site(site_id).is_portal:
        return []
    sites = {
        experiment_index_id(other): other
        for other in _component_site_ids()
        if other != site_id
    }
    hits = sorted(
        (
            hit
            for hit in await search_indexes(list(sites), query, top_k=1)
            if hit.similarity >= _MIN_SEMANTIC_SIM
        ),
        key=lambda hit: (-hit.similarity, sites[hit.index_id]),
    )[:limit]
    keys = [(sites[hit.index_id], hit.entry_id) for hit in hits]
    cards = await read_experiment_cards(keys)
    return [
        ExperimentMatch(
            card=ExperimentCard.model_validate(cards[key]), similarity=hit.similarity
        )
        for key, hit in zip(keys, hits, strict=True)
        if key in cards
    ]


async def read_experiment(site_id: str, dataset_id: str) -> ExperimentCard:
    """The card of one dataset of one site."""
    key = (site_id, dataset_id)
    cards = await read_experiment_cards([key])
    if key not in cards:
        raise UnknownExperimentError(site_id, dataset_id)
    return ExperimentCard.model_validate(cards[key])


async def sites_publishing(dataset_ids: Sequence[str]) -> dict[str, list[str]]:
    """The component sites that publish each dataset. A dataset none publishes is absent."""
    sites: defaultdict[str, list[str]] = defaultdict(list)
    for dataset_id, site_id in await dataset_sites(dataset_ids, _component_site_ids()):
        sites[dataset_id].append(site_id)
    return {dataset_id: sorted(held) for dataset_id, held in sites.items()}


async def sites_holding_organism(organism: str) -> list[str]:
    """The component sites with a dataset of this organism or of one of its strains."""
    wanted = " ".join(organism.split()).casefold()
    if not wanted:
        return []
    held = await experiment_organisms(_component_site_ids())
    return sorted(
        {
            site_id
            for site_id, organisms in held
            for named in organisms.casefold().split(ORGANISM_SEPARATOR)
            if named == wanted or named.startswith(f"{wanted} ")
        }
    )
