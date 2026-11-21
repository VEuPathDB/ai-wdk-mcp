from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError
from tests._support.recorded_searches import recorded_search
from veupathdb.domain.parameters import ParamValue, StatedValuesError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKSearchResponse

from veupathdb_mcp.catalog import (
    ParamIntent,
    Provenance,
    SiteSetParameterError,
    ValidatedParams,
    format_param_info_typed,
    resolve_params_with_intent,
    search_inspection,
)
from veupathdb_mcp.catalog.param_dag import ResolvedParams
from veupathdb_mcp.controls import IntersectionConfig
from veupathdb_mcp.controls.control_types import ControlTestResult
from veupathdb_mcp.tools import catalog_tools, user_tools

from .conftest import fetcher

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)

SEARCH = "GenesByNgsSnps"


def _snps() -> WDKSearchResponse:
    return recorded_search("search_genes_by_ngs_snps")


async def _resolve(stated: dict[str, object]) -> ResolvedParams:
    definition = _snps().search_data.parameters or []
    return await resolve_params_with_intent(
        fetch_at=fetcher(*format_param_info_typed(definition)),
        intent=ParamIntent(),
        search_name=SEARCH,
        stated=stated,
        definition=definition,
    )


async def test_a_native_number_binds_as_its_shortest_decimal() -> None:
    resolved = await _resolve(
        {
            "MinPercentMinorAlleles": 5.0,
            "organismSinglePick": ["Plasmodium falciparum 3D7"],
        }
    )

    assert resolved.params["MinPercentMinorAlleles"].to_wire() == "5"
    assert resolved.provenance["MinPercentMinorAlleles"] is Provenance.STATED


async def test_the_typed_wrapper_is_not_a_stated_shape() -> None:
    with pytest.raises(StatedValuesError) as refused:
        await _resolve({"MinPercentMinorAlleles": {"type": "string", "value": "5"}})

    assert [fault.name for fault in refused.value.faults] == ["MinPercentMinorAlleles"]


async def test_two_bad_values_are_refused_in_one_error() -> None:
    with pytest.raises(StatedValuesError) as refused:
        await _resolve({"MinPercentMinorAlleles": "five", "snp_class": "Nonsense"})

    assert sorted(fault.name for fault in refused.value.faults) == [
        "MinPercentMinorAlleles",
        "snp_class",
    ]


async def test_a_site_set_name_is_refused_before_its_value_is_read() -> None:
    with pytest.raises(SiteSetParameterError):
        await _resolve({"WebServicesPath": "x"})


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Catalog:
        async def get_search_details(
            self, ctx: object, *, expand_params: bool = True
        ) -> WDKSearchResponse:
            del ctx, expand_params
            return _snps()

    async def definition(site_id: str, rt: str, search_name: str) -> object:
        del site_id, rt, search_name
        return _snps().search_data

    infos = format_param_info_typed(_snps().search_data.parameters or [])
    monkeypatch.setattr(catalog_tools, "get_discovery_service", _Catalog)
    monkeypatch.setattr(catalog_tools, "wdk_fetch_at", lambda *args: fetcher(*infos))
    monkeypatch.setattr(search_inspection, "read_search_definition", definition)


@pytest.mark.usefixtures("served")
async def test_the_served_resolve_reads_a_native_term() -> None:
    resolved = await catalog_tools.resolve_search_parameters(
        "plasmodb", SEARCH, overrides={"ReadFrequencyPercent": "60%"}
    )

    assert resolved.params["ReadFrequencyPercent"].to_wire() == "60%"
    assert resolved.provenance["ReadFrequencyPercent"] is Provenance.STATED


@pytest.mark.usefixtures("served")
async def test_the_served_validation_reads_a_native_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, str]] = []

    async def validate(
        ctx: object, *, parameters: dict[str, ParamValue], callbacks: object
    ) -> ValidatedParams:
        del ctx, callbacks
        seen.append({name: value.to_wire() for name, value in parameters.items()})
        return ValidatedParams(params={}, record_class="transcript")

    monkeypatch.setattr(catalog_tools, "validate_parameters", validate)

    await catalog_tools.validate_search_parameters(
        "plasmodb",
        SEARCH,
        {"MinPercentMinorAlleles": 1e-8},
        record_type="transcript",
    )

    assert seen == [{"MinPercentMinorAlleles": "0.00000001"}]


@pytest.mark.usefixtures("served")
async def test_the_served_control_run_reads_its_parameters_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, str]] = []

    async def run(config: IntersectionConfig, **kwargs: object) -> ControlTestResult:
        del kwargs
        seen.append(
            {name: value.to_wire() for name, value in config.target_parameters.items()}
        )
        return ControlTestResult(site_id="plasmodb", record_type="transcript")

    monkeypatch.setattr(user_tools, "run_positive_negative_controls", run)

    await user_tools.run_control_tests_on_search(
        "plasmodb",
        SEARCH,
        {"organismSinglePick": ["Plasmodium falciparum 3D7"], "snp_class": "Coding"},
        positive_controls=["PF3D7_1222600"],
    )

    assert seen == [
        {
            "organismSinglePick": '["Plasmodium falciparum 3D7"]',
            "snp_class": "Coding",
        }
    ]


@pytest.mark.usefixtures("served")
async def test_the_served_options_read_refuses_a_wrapped_parent() -> None:
    with pytest.raises(ToolError, match="organismSinglePick"):
        await catalog_tools.get_parameter_options(
            "plasmodb",
            SEARCH,
            "variation_sample_meta",
            record_type="transcript",
            context_values={
                "organismSinglePick": {"type": "multi-pick-vocabulary", "values": []}
            },
        )
