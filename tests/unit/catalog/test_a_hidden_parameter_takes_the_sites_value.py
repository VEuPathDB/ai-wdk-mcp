from __future__ import annotations

import pytest
from tests._support.recorded_searches import recorded_search
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import to_wire
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKRecordType, WDKSearch, WDKSearchResponse

from veupathdb_mcp.catalog import param_validation, validate_parameters

from .conftest import no_dependent_refresh, validation_callbacks

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)

CTX = SearchContext(
    site_id="plasmodb", record_type="transcript", search_name="GenesByNgsSnps"
)
DEFAULTS = {"eda_sample_table_suffix": "s3be28bbe14_sample", "WebServicesPath": "dflt"}


def _published() -> WDKSearchResponse:
    return recorded_search("search_genes_by_ngs_snps")


class _Site:
    def __init__(self) -> None:
        self.contexts: list[dict[str, str]] = []

    async def get_search_details_with_params(
        self,
        record_type: str,
        search_name: str,
        context: dict[str, str] | None = None,
        *,
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        del record_type, search_name, expand_params
        self.contexts.append(dict(context or {}))
        return _published()


class _Catalog:
    async def get_search_details(
        self, ctx: SearchContext, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del ctx, expand_params
        return _published()

    async def get_record_types(self, site_id: str) -> list[WDKRecordType]:
        del site_id
        return [WDKRecordType(url_segment="transcript")]

    async def get_searches(self, site_id: str, record_type: str) -> list[WDKSearch]:
        del site_id, record_type
        return [WDKSearch(url_segment="GenesByNgsSnps")]


async def test_the_values_sent_for_a_search_carry_each_hidden_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _Site()
    monkeypatch.setattr(param_validation, "get_wdk_client", lambda site_id: site)
    monkeypatch.setattr(param_validation, "get_discovery_service", _Catalog)
    monkeypatch.setattr(
        param_validation, "get_refreshed_dependent_params", no_dependent_refresh
    )

    validated = await validate_parameters(
        CTX, parameters={}, callbacks=validation_callbacks()
    )

    assert {name: to_wire(validated.params[name]) for name in DEFAULTS} == DEFAULTS
    assert site.contexts == [DEFAULTS]
    assert set(DEFAULTS) <= set(validated.substituted)
