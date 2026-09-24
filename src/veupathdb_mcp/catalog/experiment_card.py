"""One WDK dataset record of one site, as a card a host shows beside its own searches."""

from __future__ import annotations

import re

from pydantic import ConfigDict, Field, field_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.embeddings.experiment_index import ExperimentEntry
from veupathdb_mcp.embeddings.semantic_index import strip_markup

# The cut the host applies to a study description it shows.
SUMMARY_LIMIT = 600
LINE_LIMIT = 160
ORGANISM_SEPARATOR = "; "

_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ELLIPSIS = "..."


def _plain(text: str) -> str:
    """The text without markup, on one line."""
    return " ".join(strip_markup(text).split())


class ExperimentCard(CamelModel):
    """A dataset of one site: what it measured, in what, by whom, and what it feeds."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    site_id: str
    dataset_id: str
    name: str
    organism: str
    assay: str
    attribution: str = ""
    summary: str = ""
    pmids: list[str] = Field(default_factory=list)
    searches: list[str] = Field(default_factory=list)
    record_url: str

    @field_validator("name", "assay", "attribution")
    @classmethod
    def _without_markup(cls, value: str) -> str:
        return _plain(value)

    @field_validator("organism")
    @classmethod
    def _one_organism_per_break(cls, value: str) -> str:
        """WDK breaks a list of organisms with a tag, so each one is kept apart."""
        organisms = (_plain(part) for part in _BREAK.split(value))
        return ORGANISM_SEPARATOR.join(organism for organism in organisms if organism)

    @field_validator("summary")
    @classmethod
    def _cut_summary(cls, value: str) -> str:
        return _plain(value)[:SUMMARY_LIMIT]

    def line(self) -> str:
        """The site, the organism, the assay and the name, on one short line."""
        organisms = self.organism.split(ORGANISM_SEPARATOR) if self.organism else []
        where = organisms[0] if organisms else ""
        if len(organisms) > 1:
            where = f"{where} and {len(organisms) - 1} more"
        title = f"{self.name} ({self.attribution})" if self.attribution else self.name
        text = " | ".join(
            part for part in (self.site_id, where, self.assay, title) if part
        )
        if len(text) <= LINE_LIMIT:
            return text
        return text[: LINE_LIMIT - len(_ELLIPSIS)] + _ELLIPSIS

    def index_text(self) -> str:
        """The text the site's experiment index finds this card by, names first."""
        parts = (self.name, self.organism, self.assay, self.attribution, self.summary)
        return " ".join(part for part in parts if part)

    def index_entry(self) -> ExperimentEntry:
        """The card as the experiment index stores it."""
        return ExperimentEntry(
            dataset_id=self.dataset_id,
            text=self.index_text(),
            card=self.model_dump(mode="json", by_alias=True),
        )
