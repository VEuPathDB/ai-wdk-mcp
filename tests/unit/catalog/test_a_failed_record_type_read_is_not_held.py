from __future__ import annotations

import pytest
from veupathdb.errors import WDKError
from veupathdb.wdk import WDKRecordType

from veupathdb_mcp.catalog import site_record_types


class _NoCatalog:
    def held_record_types(self, site_id: str) -> None:
        del site_id


class _Flaky:
    def __init__(self) -> None:
        self.reads = 0

    async def get_record_types(self) -> list[WDKRecordType]:
        self.reads += 1
        if self.reads == 1:
            msg = "the site did not answer"
            raise WDKError(msg, status=502)
        return [WDKRecordType(url_segment="helper")]


async def test_a_failed_read_is_raised_and_the_next_call_reads_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _Flaky()
    monkeypatch.setattr(site_record_types, "_LISTED", {})
    monkeypatch.setattr(site_record_types, "get_discovery_service", _NoCatalog)
    monkeypatch.setattr(site_record_types, "get_wdk_client", lambda _site: site)

    with pytest.raises(WDKError):
        await site_record_types.declared_record_types("orthomcl")

    assert await site_record_types.declared_record_types("orthomcl") == {"helper"}
    assert await site_record_types.declared_record_types("orthomcl") == {"helper"}
    assert site.reads == 2
