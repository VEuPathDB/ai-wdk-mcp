"""Disk cache for catalog metadata snapshots."""

import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from veupathdb import get_logger
from veupathdb.wdk import SiteInfo, WDKRecordType, WDKSearch

from veupathdb_mcp.catalog.experiment_card import ExperimentCard

logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# The shape of the file two images exchange through the catalogs volume. Raise
# it whenever a field changes meaning, is added or is dropped.
SNAPSHOT_FORMAT_VERSION = 2


class CatalogSnapshot(BaseModel):
    """A snapshot of one site's catalog metadata."""

    model_config = ConfigDict(extra="ignore")

    format_version: int | None = None
    cached_at: float = Field(default_factory=time.time)
    record_types: list[WDKRecordType]
    searches: dict[str, list[WDKSearch]]
    datasets: list[ExperimentCard]
    search_categories: dict[str, str]
    search_category_labels: dict[str, str] = Field(default_factory=dict)
    available_categories: list[str]
    # Serialized length of this snapshot, the scale of the strings a loaded
    # catalog holds. Excluded from the file it describes.
    payload_bytes: int = Field(default=0, exclude=True)

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.cached_at) > _CACHE_TTL_SECONDS


def catalog_cache_path(site_id: str, cache_dir: Path) -> Path:
    return cache_dir / f"{site_id}.json"


def try_load_catalog_cache(site_id: str, cache_dir: Path) -> CatalogSnapshot | None:
    """Loads a cached snapshot. A missing or unreadable file returns None."""
    path = catalog_cache_path(site_id, cache_dir)
    if not path.exists():
        return None
    try:
        raw = path.read_text()
        snapshot = CatalogSnapshot.model_validate_json(raw)
    except OSError, ValueError, json.JSONDecodeError:
        logger.debug("Catalog cache load failed", path=str(path))
        return None
    if snapshot.format_version != SNAPSHOT_FORMAT_VERSION:
        logger.warning(
            "Catalog snapshot format differs",
            path=str(path),
            found=snapshot.format_version,
            expected=SNAPSHOT_FORMAT_VERSION,
        )
        return None
    snapshot.payload_bytes = len(raw.encode())
    return snapshot


def save_catalog_cache(
    site_id: str, snapshot: CatalogSnapshot, cache_dir: Path
) -> None:
    """Writes a catalog snapshot to disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = catalog_cache_path(site_id, cache_dir)
    snapshot.format_version = SNAPSHOT_FORMAT_VERSION
    payload = snapshot.model_dump_json(by_alias=True)
    snapshot.payload_bytes = len(payload.encode())
    try:
        path.write_text(payload)
    except OSError:
        logger.warning("Failed to save catalog cache", path=str(path), exc_info=True)


# The models below parse the WDK dataset report.

# The record class of the searches a gene strategy binds.
_GENE_RECORD_CLASS = "TranscriptRecordClasses.TranscriptRecordClass"


class DatasetPkPart(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    value: str = ""


class DatasetAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore")
    display_name: str = ""
    type: str = ""
    newcategory: str = ""
    organism_prefix: str = ""
    short_attribution: str = ""
    summary: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def _absent_is_empty(cls, value: str | None) -> str:
        return value or ""


class DatasetReference(BaseModel):
    """One row of the References table: a WDK object the dataset feeds."""

    model_config = ConfigDict(extra="ignore")
    target_type: str = ""
    target_name: str = ""
    record_type: str = ""

    @property
    def gene_search(self) -> str | None:
        """The url segment of the gene search this row names, if it names one."""
        if self.target_type != "question" or self.record_type != _GENE_RECORD_CLASS:
            return None
        return self.target_name.rpartition(".")[2]


class DatasetPublication(BaseModel):
    """One row of the Publications table. A row cited by a DOI alone has no PMID."""

    model_config = ConfigDict(extra="ignore")
    pmid: str | None = None


class DatasetTables(BaseModel):
    model_config = ConfigDict(extra="ignore")
    references: list[DatasetReference] = Field(default_factory=list, alias="References")
    publications: list[DatasetPublication] = Field(
        default_factory=list, alias="Publications"
    )


class DatasetRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: list[DatasetPkPart] = Field(default_factory=list)
    attributes: DatasetAttributes = Field(default_factory=DatasetAttributes)
    tables: DatasetTables = Field(default_factory=DatasetTables)

    @property
    def dataset_id(self) -> str:
        for part in self.id:
            if part.name == "dataset_id":
                return part.value
        return self.id[0].value if self.id else ""

    def card(self, site: SiteInfo) -> ExperimentCard:
        """The record as a card of the site that published it."""
        searches = (reference.gene_search for reference in self.tables.references)
        pmids = (publication.pmid for publication in self.tables.publications)
        attributes = self.attributes
        return ExperimentCard(
            site_id=site.id,
            dataset_id=self.dataset_id,
            name=attributes.display_name,
            organism=attributes.organism_prefix,
            assay=attributes.newcategory or attributes.type,
            attribution=attributes.short_attribution,
            summary=attributes.summary,
            pmids=list(dict.fromkeys(pmid for pmid in pmids if pmid)),
            searches=list(dict.fromkeys(name for name in searches if name)),
            record_url=f"{site.web_base_url}/app/record/dataset/{self.dataset_id}",
        )


class DatasetReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    records: list[DatasetRecord] = Field(default_factory=list)
