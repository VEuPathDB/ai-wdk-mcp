from __future__ import annotations

import pytest
from pydantic import TypeAdapter
from tests._support.filter_reads import FilterReadsDouble
from tests._support.recorded_searches import recorded_search
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    FilterStatementError,
    FilterValue,
    MultiPickValue,
    to_wire,
)
from veupathdb.errors import WDKError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import (
    WDKParameter,
    WDKRecordType,
    WDKSearch,
    WDKSearchResponse,
)

from veupathdb_mcp.catalog import (
    ParamIntent,
    Provenance,
    format_param_info_typed,
    param_validation,
    resolve_params_with_intent,
    validate_parameters,
)
from veupathdb_mcp.catalog.param_dag import _defer_to_next_pass
from veupathdb_mcp.catalog.param_formatting import ParameterInfo

from .conftest import validation_callbacks

pytestmark = pytest.mark.skipif(
    any(
        needs_qa_recording(f"wdk/{name}.json")
        for name in (
            "search_genes_by_ngs_snps",
            "search_genes_by_ngs_snps_under_another_organism",
            "refresh_ngs_snps_on_organism",
        )
    ),
    reason=NEEDS_QA_RECORDING,
)

CTX = SearchContext(
    site_id="plasmodb", record_type="transcript", search_name="GenesByNgsSnps"
)
VIVAX = "Plasmodium vivax P01"
_WDK_500 = "Internal Error"
_REFRESHED: TypeAdapter[list[WDKParameter]] = TypeAdapter(list[WDKParameter])


def _published() -> WDKSearchResponse:
    return recorded_search("search_genes_by_ngs_snps")


def _under_vivax() -> WDKSearchResponse:
    """The vivax definition; its recording was judged with only the organism set."""
    read = recorded_search("search_genes_by_ngs_snps_under_another_organism")
    return read.model_copy(update={"validation": _published().validation})


class _Site:
    def __init__(self, *, reads: bool) -> None:
        self._reads = reads

    async def get_search_details_with_params(
        self,
        record_type: str,
        search_name: str,
        context: dict[str, str] | None = None,
        *,
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        del record_type, search_name, context, expand_params
        if not self._reads:
            raise WDKError(_WDK_500, status=500)
        return _under_vivax()


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


async def _refresh_on_organism(
    ctx: SearchContext, *, parameter_name: str, context_values: object
) -> list[WDKParameter]:
    del ctx, context_values
    if parameter_name != "organismSinglePick":
        return []
    return _REFRESHED.validate_python(
        load_recorded("refresh_ngs_snps_on_organism").json_body()
    )


@pytest.mark.parametrize("reads", [True, False], ids=["read", "refused-read"])
async def test_a_site_set_dependent_is_sent_at_the_value_read_under_its_parent(
    monkeypatch: pytest.MonkeyPatch, *, reads: bool
) -> None:
    monkeypatch.setattr(
        param_validation, "get_wdk_client", lambda site_id: _Site(reads=reads)
    )
    monkeypatch.setattr(param_validation, "get_discovery_service", _Catalog)
    monkeypatch.setattr(
        param_validation, "get_refreshed_dependent_params", _refresh_on_organism
    )

    validated = await validate_parameters(
        CTX,
        stated={"organismSinglePick": MultiPickValue(values=[VIVAX])},
        callbacks=validation_callbacks(),
        about=None,
    )

    assert to_wire(validated.params["eda_sample_table_suffix"]) == "sba1cd4a562_sample"


def _sample_meta() -> ParameterInfo:
    params = _published().search_data.parameters or []
    (info,) = [
        info
        for info in format_param_info_typed(params)
        if info.name == "variation_sample_meta"
    ]
    return info


@pytest.mark.parametrize(
    ("context", "resolved_this_pass", "deferred"),
    [
        ({"organismSinglePick": "x"}, set(), True),
        ({"organismSinglePick": "x", "eda_sample_table_suffix": "y"}, set(), False),
        (
            {"organismSinglePick": "x", "eda_sample_table_suffix": "y"},
            {"eda_sample_table_suffix"},
            True,
        ),
    ],
)
def test_a_dependent_waits_for_every_wire_parent(
    context: dict[str, str], resolved_this_pass: set[str], *, deferred: bool
) -> None:
    assert (
        _defer_to_next_pass(
            _sample_meta(), context=context, resolved_this_pass=resolved_this_pass
        )
        is deferred
    )


async def _by_organism(context: dict[str, str]) -> list[WDKParameter]:
    read = _under_vivax() if VIVAX in context.get("organismSinglePick", "") else None
    return (read or _published()).search_data.parameters or []


def _samples(organism: str) -> dict[str, object]:
    return {
        "organismSinglePick": [organism],
        "variation_sample_meta": [{"field": "VAR_c4c428f1", "value": ["mosquitoes"]}],
    }


async def test_a_facet_statement_binds_under_its_stated_organism() -> None:
    resolved = await resolve_params_with_intent(
        filter_reads=FilterReadsDouble(),
        fetch_at=_by_organism,
        intent=ParamIntent(),
        search_name=CTX.search_name,
        stated=_samples(VIVAX),
        about=None,
    )

    value = resolved.params["variation_sample_meta"]
    assert isinstance(value, FilterValue)
    assert [(c.field, c.value) for c in value.filters] == [
        ("VAR_c4c428f1", ["mosquitoes"])
    ]
    assert resolved.provenance["variation_sample_meta"] is Provenance.STATED


async def test_the_same_statement_under_another_organism_is_refused() -> None:
    with pytest.raises(FilterStatementError, match="VAR_c4c428f1"):
        await resolve_params_with_intent(
            filter_reads=FilterReadsDouble(),
            fetch_at=_by_organism,
            intent=ParamIntent(),
            search_name=CTX.search_name,
            stated=_samples("Plasmodium falciparum 3D7"),
            about=None,
        )
