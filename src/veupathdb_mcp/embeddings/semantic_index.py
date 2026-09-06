"""Semantic search index over enriched WDK search descriptions.

The vectors live in the shared record manager, addressed by the text that
produced them, so a catalog change embeds only the entries that changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from veupathdb.wdk.wdk_models import WDKSearch

from veupathdb_mcp.embeddings.record_manager import (
    IndexEntry,
    SyncReport,
    search_index,
    sync_index,
)
from veupathdb_mcp.embeddings.settings import get_embedding_settings

_TAG = re.compile(r"<[^>]+>")

_WEIGHT_ATTRIBUTE = "Search Weight"


def enriched_text_limit() -> int:
    """Characters of an entry's text the index reads.

    The embedder cuts every input at this limit, so an entry is addressed by
    the text the API actually reads.
    """
    return get_embedding_settings().embedding_input_char_limit


def catalog_index_id(site_id: str) -> str:
    """The record manager's id for one site's search catalog."""
    return f"catalog:{site_id}"


def strip_markup(text: str) -> str:
    """The text without its inline markup."""
    return _TAG.sub(" ", text)


def _format_param_names(param_names: list[str]) -> str:
    """Convert param names from snake_case to readable words."""
    if not param_names:
        return ""
    return " ".join(name.replace("_", " ") for name in param_names)


@dataclass(frozen=True, slots=True)
class SearchIndexEntry:
    """A single entry in the semantic search index."""

    search_name: str
    record_type: str
    enriched_text: str

    @property
    def entry_id(self) -> str:
        """The record manager's id for this search, which carries its type."""
        return f"{self.record_type}/{self.search_name}"


@dataclass
class SemanticSearchIndex:
    """One site's searches, ranked by cosine similarity in Postgres."""

    site_id: str = ""
    entries: list[SearchIndexEntry] = field(default_factory=list)

    def collect(
        self,
        searches_by_rt: dict[str, list[WDKSearch]],
        category_labels: dict[str, str] | None = None,
    ) -> None:
        """Hold one entry per search. Reads no store and opens no connection."""
        cats = category_labels or {}
        self.entries = sorted(
            (
                SearchIndexEntry(
                    search_name=search.url_segment,
                    record_type=rt_name,
                    enriched_text=self._build_enriched_text(search, cats),
                )
                for rt_name, searches in searches_by_rt.items()
                for search in searches
            ),
            key=lambda entry: (entry.record_type, entry.search_name),
        )

    async def sync(self) -> SyncReport:
        """Write the collected entries to the store, embedding only what is new."""
        if not self.entries:
            return SyncReport()
        return await sync_index(
            catalog_index_id(self.site_id),
            [
                IndexEntry(entry_id=entry.entry_id, text=entry.enriched_text)
                for entry in self.entries
            ],
        )

    async def query(
        self,
        query_text: str,
        top_k: int = 20,
    ) -> list[tuple[str, str, float]]:
        """The top-k searches as (search_name, record_type, cosine similarity)."""
        hits = await search_index(catalog_index_id(self.site_id), query_text, top_k)
        results: list[tuple[str, str, float]] = []
        for hit in hits:
            record_type, _, search_name = hit.entry_id.partition("/")
            if search_name:
                results.append((search_name, record_type, hit.similarity))
        return results

    def _build_enriched_text(
        self,
        search: WDKSearch,
        category_labels: dict[str, str],
    ) -> str:
        """Build the enriched text for a search.

        The most discriminating signals come first, because the text is cut.
        """
        parts: list[str] = []

        cat = category_labels.get(search.url_segment, "")
        if cat:
            parts.append(cat)

        parts.extend(
            " ".join(str(v) for v in prop_values)
            for prop_values in search.properties.values()
            if prop_values
        )

        parts.append(search.display_name)
        if (
            search.short_display_name
            and search.short_display_name != search.display_name
        ):
            parts.append(search.short_display_name)

        if search.summary:
            parts.append(search.summary)

        parts.extend(g.display_name for g in search.groups if g.display_name)

        param_text = _format_param_names(search.param_names)
        if param_text:
            parts.append(param_text)

        name_words = " ".join(
            re.findall(r"[A-Z][a-z]+|[a-z]+|[A-Z]+|\d+", search.url_segment)
        )
        parts.append(name_words)

        parts.append(strip_markup(search.description))

        # Every search carries the weight attribute, so it separates none of them.
        parts.extend(
            attr.display_name
            for attr in search.dynamic_attributes
            if attr.display_name and attr.display_name != _WEIGHT_ATTRIBUTE
        )

        return " ".join(p for p in parts if p).strip()[: enriched_text_limit()]
