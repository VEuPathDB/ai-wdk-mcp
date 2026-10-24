from collections.abc import Mapping, Sequence

import pytest
from veupathdb.wdk import WDKRecordType, WDKSearch

from veupathdb_mcp.catalog import searches

type Listing = Mapping[str, Sequence[str]]


class ListedCatalog:
    def __init__(self, listing: Listing) -> None:
        self._listing = listing

    def find_record_type_for_search(self, search_name: str) -> str | None:
        return next(
            (rt for rt, names in self._listing.items() if search_name in names), None
        )

    def get_record_types(self) -> list[WDKRecordType]:
        return [WDKRecordType(url_segment=rt) for rt in self._listing]

    def get_searches(self, record_type: str) -> list[WDKSearch]:
        return [
            WDKSearch.model_validate({"urlSegment": name})
            for name in self._listing[record_type]
        ]


class ListedDiscovery:
    def __init__(self, listing: Listing) -> None:
        self._catalog = ListedCatalog(listing)

    async def get_catalog(self, site_id: str) -> ListedCatalog:
        del site_id
        return self._catalog


def list_searches(monkeypatch: pytest.MonkeyPatch, listing: Listing) -> None:
    discovery = ListedDiscovery(listing)
    monkeypatch.setattr(searches, "get_discovery_service", lambda: discovery)
