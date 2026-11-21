from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from fastmcp.exceptions import ToolError
from pydantic import JsonValue
from tests._support.recorded_searches import recorded_search
from veupathdb.domain.parameters import ParamValue, StatedValuesError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog import (
    ParameterInfo,
    ParamIntent,
    Provenance,
    SiteSetParameterError,
    ValidatedParams,
    resolve_params_with_intent,
    search_inspection,
)
from veupathdb_mcp.catalog.param_dag import ResolvedParams
from veupathdb_mcp.controls import IntersectionConfig
from veupathdb_mcp.controls.control_types import ControlTestResult
from veupathdb_mcp.tools import catalog_tools, user_tools

pytestmark = pytest.mark.skipif(
    needs_qa_recording(
        "wdk/search_genes_by_ngs_snps.json",
        "wdk/search_genes_by_ngs_snps_under_another_organism.json",
    ),
    reason=NEEDS_QA_RECORDING,
)

SEARCH = "GenesByNgsSnps"
VIVAX = "Plasmodium vivax P01"
VIVAX_SAMPLES: dict[str, JsonValue] = {
    "organismSinglePick": [VIVAX],
    "variation_sample_meta": [{"field": "VAR_c4c428f1", "value": ["mosquitoes"]}],
}


async def by_organism(context: dict[str, str]) -> list[WDKParameter]:
    """The search as WDK answers it under the organism the context names."""
    name = (
        "search_genes_by_ngs_snps_under_another_organism"
        if VIVAX in context.get("organismSinglePick", "")
        else "search_genes_by_ngs_snps"
    )
    return recorded_search(name).search_data.parameters or []


async def _resolve(stated: dict[str, JsonValue]) -> ResolvedParams:
    return await resolve_params_with_intent(
        fetch_at=by_organism, intent=ParamIntent(), search_name=SEARCH, stated=stated
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
    monkeypatch.setattr(catalog_tools, "wdk_fetch_at", lambda *args: by_organism)
    monkeypatch.setattr(search_inspection, "wdk_fetch_at", lambda *args: by_organism)


@pytest.fixture
def validated(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []

    async def validate(
        ctx: object, *, parameters: dict[str, ParamValue], callbacks: object
    ) -> ValidatedParams:
        del ctx, callbacks
        seen.append({name: value.to_wire() for name, value in parameters.items()})
        return ValidatedParams(params={}, record_class="transcript")

    monkeypatch.setattr(catalog_tools, "validate_parameters", validate)
    return seen


@pytest.fixture
def controlled(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []

    async def run(config: IntersectionConfig, **kwargs: object) -> ControlTestResult:
        del kwargs
        seen.append(
            {name: value.to_wire() for name, value in config.target_parameters.items()}
        )
        return ControlTestResult(site_id="plasmodb", record_type="transcript")

    monkeypatch.setattr(user_tools, "run_positive_negative_controls", run)
    return seen


@pytest.mark.usefixtures("served")
async def test_the_served_resolve_reads_a_native_term() -> None:
    resolved = await catalog_tools.resolve_search_parameters(
        "plasmodb", SEARCH, overrides={"ReadFrequencyPercent": "60%"}
    )

    assert resolved.params["ReadFrequencyPercent"].to_wire() == "60%"
    assert resolved.provenance["ReadFrequencyPercent"] is Provenance.STATED


@pytest.mark.usefixtures("served")
async def test_the_served_validation_reads_a_native_value(
    validated: list[dict[str, str]],
) -> None:
    await catalog_tools.validate_search_parameters(
        "plasmodb", SEARCH, {"MinPercentMinorAlleles": 1e-8}, record_type="transcript"
    )

    assert validated == [{"MinPercentMinorAlleles": "0.00000001"}]


@pytest.mark.usefixtures("served")
async def test_the_served_validation_binds_a_facet_under_its_stated_parent(
    validated: list[dict[str, str]],
) -> None:
    await catalog_tools.validate_search_parameters(
        "plasmodb", SEARCH, VIVAX_SAMPLES, record_type="transcript"
    )

    [values] = validated
    assert '"field": "VAR_c4c428f1"' in values["variation_sample_meta"]
    assert '"value": ["mosquitoes"]' in values["variation_sample_meta"]


@pytest.mark.usefixtures("served")
async def test_the_served_options_read_shows_the_facets_under_its_parent() -> None:
    read = await catalog_tools.get_parameter_options(
        "plasmodb",
        SEARCH,
        "variation_sample_meta",
        record_type="transcript",
        context_values={
            "organismSinglePick": [VIVAX],
            "eda_sample_table_suffix": "sba1cd4a562_sample",
        },
    )

    assert isinstance(read, ParameterInfo)
    assert "VAR_c4c428f1" in {facet.term for facet in read.facets().root}


@pytest.mark.usefixtures("served")
async def test_the_served_control_run_reads_its_parameters_first(
    controlled: list[dict[str, str]],
) -> None:
    await user_tools.run_control_tests_on_search(
        "plasmodb",
        SEARCH,
        {"organismSinglePick": ["Plasmodium falciparum 3D7"], "snp_class": "Coding"},
        positive_controls=["PF3D7_1222600"],
    )

    assert controlled == [
        {
            "organismSinglePick": '["Plasmodium falciparum 3D7"]',
            "snp_class": "Coding",
        }
    ]


Served = Callable[[dict[str, JsonValue]], Awaitable[object]]


def _resolve_served(stated: dict[str, JsonValue]) -> Awaitable[object]:
    return catalog_tools.resolve_search_parameters("plasmodb", SEARCH, overrides=stated)


def _validate_served(stated: dict[str, JsonValue]) -> Awaitable[object]:
    return catalog_tools.validate_search_parameters(
        "plasmodb", SEARCH, stated, record_type="transcript"
    )


def _control_served(stated: dict[str, JsonValue]) -> Awaitable[object]:
    return user_tools.run_control_tests_on_search(
        "plasmodb", SEARCH, stated, positive_controls=["PF3D7_1222600"]
    )


def _options_served(stated: dict[str, JsonValue]) -> Awaitable[object]:
    return catalog_tools.get_parameter_options(
        "plasmodb", SEARCH, "snp_class", record_type="transcript", context_values=stated
    )


@pytest.mark.usefixtures("served", "validated", "controlled")
@pytest.mark.parametrize(
    "tool", [_resolve_served, _validate_served, _control_served, _options_served]
)
@pytest.mark.parametrize(
    ("stated", "named"),
    [
        (
            {"MinPercentMinorAlleles": {"type": "string", "value": "5"}},
            "MinPercentMinorAlleles",
        ),
        (
            {"variation_sample_meta": "VAR_338f1760=2020-01-01..2020-12-31"},
            "variation_sample_meta",
        ),
        (
            {"MinPercentMinorAlleleZ": 5, "snp_class": "Coding"},
            "MinPercentMinorAlleleZ",
        ),
    ],
    ids=["wrapper", "shorthand", "misspelled"],
)
async def test_every_served_read_refuses_by_name(
    tool: Served, stated: dict[str, JsonValue], named: str
) -> None:
    with pytest.raises(ToolError, match=named):
        await tool(stated)
