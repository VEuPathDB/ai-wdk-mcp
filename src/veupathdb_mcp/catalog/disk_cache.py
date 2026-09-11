"""Disk cache for catalog metadata snapshots."""

import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from veupathdb import get_logger
from veupathdb.wdk import WDKRecordType, WDKSearch

logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# The shape of the file two images exchange through the catalogs volume. Raise
# it whenever a field changes meaning, is added or is dropped.
SNAPSHOT_FORMAT_VERSION = 1


class CatalogSnapshot(BaseModel):
    """A snapshot of one site's catalog metadata."""

    model_config = ConfigDict(extra="ignore")

    format_version: int | None = None
    cached_at: float = Field(default_factory=time.time)
    record_types: list[WDKRecordType]
    searches: dict[str, list[WDKSearch]]
    dataset_summaries: dict[str, str]
    dataset_contacts: dict[str, str]
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


class DatasetPkPart(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    value: str = ""


class DatasetAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str | None = None
    contact: str | None = None


class DatasetRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: list[DatasetPkPart] = Field(default_factory=list)
    attributes: DatasetAttributes = Field(default_factory=DatasetAttributes)

    @property
    def dataset_id(self) -> str:
        for part in self.id:
            if part.name == "dataset_id":
                return part.value
        return self.id[0].value if self.id else ""

    def populate(
        self,
        summaries: dict[str, str],
        contacts: dict[str, str],
    ) -> None:
        """Writes this record's summary and contact into the given maps."""
        ds_id = self.dataset_id
        if not ds_id:
            return
        if self.attributes.summary:
            summaries[ds_id] = self.attributes.summary
        if self.attributes.contact:
            contacts[ds_id] = self.attributes.contact


class DatasetReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    records: list[DatasetRecord] = Field(default_factory=list)
