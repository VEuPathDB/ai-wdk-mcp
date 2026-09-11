"""The tools veupathdb-wdk-mcp serves, what each claims, and how a call is credentialed."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.types import TextContent, Tool
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import InputDatasetValue, ParamValue, StringValue
from veupathdb.domain.strategy import StrategyAst, StrategyStepNode
from veupathdb.errors import ValidationError
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import (
    AiExpressionReport,
    NewStepSpec,
    WDKIdentifier,
    WDKSearch,
    WDKStepTree,
    WDKStringParam,
)

from veupathdb_mcp import server
from veupathdb_mcp.auth import CredentialMode, McpCredential
from veupathdb_mcp.catalog import search_inspection, sites
from veupathdb_mcp.catalog.models import RecordTypeInfo
from veupathdb_mcp.catalog.overview_formatting import SearchOverviewResult
from veupathdb_mcp.catalog.param_dag import ResolvedParams, UnknownParameterError
from veupathdb_mcp.catalog.param_intent import ParamIntent
from veupathdb_mcp.catalog.param_validation import ValidatedParams
from veupathdb_mcp.catalog.search_inspection import (
    SearchInspection,
    UnknownSearchError,
)
from veupathdb_mcp.controls.control_types import ControlTestResult
from veupathdb_mcp.embeddings.errors import SemanticIndexUnavailableError
from veupathdb_mcp.embeddings.record_manager import IndexHit
from veupathdb_mcp.gene_lookup import GeneResolveResult
from veupathdb_mcp.tool_meta import (
    MAX_CALL_SECONDS_META_KEY,
    STREAM_PART_META_KEY,
)
from veupathdb_mcp.tools import catalog_tools, user_tools
from veupathdb_mcp.wdk import ai_expression, gene_set_steps, step_preview

SITE = "plasmodb"

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
ADDITIVE_WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "openWorldHint": False,
}

# One row per tool of the published inventory. This mapping is the pin.
EXPECTED_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "list_record_types": READ_ONLY,
    "search_for_searches": READ_ONLY,
    "browse_search_categories": READ_ONLY,
    "list_searches": READ_ONLY,
    "list_transforms": READ_ONLY,
    "lookup_phyletic_codes": READ_ONLY,
    "search_example_plans": READ_ONLY,
    "get_search_overview": READ_ONLY,
    "get_parameter_options": READ_ONLY,
    "lookup_gene_records": READ_ONLY,
    "get_ai_expression_summary": READ_ONLY,
    "resolve_gene_ids_to_records": READ_ONLY,
    "get_step_estimated_size": READ_ONLY,
    "get_step_sample_records": READ_ONLY,
    "get_step_download_url": READ_ONLY,
    "get_search_param_specs": READ_ONLY,
    "resolve_search_parameters": READ_ONLY,
    "validate_search_parameters": READ_ONLY,
    "search_catalog_index": READ_ONLY,
    "get_step_gene_ids": READ_ONLY,
    "run_control_tests_on_step": READ_ONLY,
    "count_plan_steps": ADDITIVE_WRITE,
    "create_gene_set_step": ADDITIVE_WRITE,
    "run_control_tests_on_search": ADDITIVE_WRITE,
    "enrich_gene_ids": ADDITIVE_WRITE,
}

# The in-process names the inventory renamed. A served copy would be a second name.
RETIRED_NAMES = ("get_estimated_size", "get_sample_records", "get_download_url")


def _service_credential() -> McpCredential:
    return McpCredential(
        token="service-secret",
        client_id="gene-page",
        scopes=[],
        mode=CredentialMode.SERVICE,
    )


def _user_credential(
    token: str, subject: str = "researcher@example.org"
) -> McpCredential:
    return McpCredential(
        token=token,
        client_id=subject,
        scopes=[],
        mode=CredentialMode.VEUPATHDB_USER,
    )


@asynccontextmanager
async def _served(credential: McpCredential | None) -> AsyncIterator[Client]:
    """A client on the server, carrying the credential a gate would have verified."""
    user = AuthenticatedUser(credential) if credential is not None else None
    reset = auth_context_var.set(user)
    try:
        async with Client(server.build_server()) as client:
            yield client
    finally:
        auth_context_var.reset(reset)


async def _list_tools() -> dict[str, Tool]:
    async with _served(None) as client:
        return {tool.name: tool for tool in await client.list_tools()}


def _error_text(result: CallToolResult) -> str:
    return " ".join(
        block.text for block in result.content if isinstance(block, TextContent)
    )


async def test_the_served_inventory_is_the_published_one() -> None:
    tools = await _list_tools()

    assert sorted(tools) == sorted(EXPECTED_ANNOTATIONS)


async def test_no_tool_keeps_the_name_the_inventory_renamed() -> None:
    tools = await _list_tools()

    assert [name for name in RETIRED_NAMES if name in tools] == []


async def test_every_tool_declares_the_annotations_the_inventory_assigns() -> None:
    tools = await _list_tools()

    declared = {
        name: (
            tool.annotations.model_dump(exclude_none=True) if tool.annotations else {}
        )
        for name, tool in tools.items()
    }
    assert declared == EXPECTED_ANNOTATIONS


async def test_run_control_tests_on_search_declares_a_non_destructive_write() -> None:
    tools = await _list_tools()

    annotations = tools["run_control_tests_on_search"].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False


async def test_every_tool_carries_a_description() -> None:
    tools = await _list_tools()

    assert [
        name for name, tool in tools.items() if not (tool.description or "").strip()
    ] == []


async def test_every_input_schema_is_an_object_that_takes_a_site() -> None:
    tools = await _list_tools()

    for name, tool in tools.items():
        assert tool.inputSchema.get("type") == "object", name
        assert "site_id" in tool.inputSchema.get("properties", {}), name
        assert "site_id" in tool.inputSchema.get("required", []), name


async def test_get_step_sample_records_takes_the_record_type_as_an_argument() -> None:
    tools = await _list_tools()

    schema = tools["get_step_sample_records"].inputSchema
    assert "record_type" in schema["required"]


async def test_a_sample_read_declares_its_bound_and_refuses_a_call_past_it() -> None:
    tools = await _list_tools()
    assert (
        tools["get_step_sample_records"].inputSchema["properties"]["limit"]["maximum"]
        == 100
    )

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "get_step_sample_records",
            {
                "site_id": SITE,
                "wdk_step_id": 1,
                "record_type": "transcript",
                "limit": 1000,
            },
            raise_on_error=False,
        )

    assert result.is_error
    assert "limit" in _error_text(result)


async def test_every_tool_with_a_typed_result_declares_an_output_schema() -> None:
    tools = await _list_tools()

    assert [name for name, tool in tools.items() if tool.outputSchema is None] == []


async def test_enrich_gene_ids_declares_its_stream_part_and_its_budget() -> None:
    tools = await _list_tools()

    tool = tools["enrich_gene_ids"]
    assert tool.meta is not None
    assert tool.meta[STREAM_PART_META_KEY] == {
        "kind": "data-wdk.enrichment-results",
        "version": 1,
    }
    assert tool.meta[MAX_CALL_SECONDS_META_KEY] > 60
    assert tool.outputSchema is not None


async def test_the_ai_expression_schema_admits_a_count_the_site_did_not_send() -> None:
    tools = await _list_tools()

    schema = tools["get_ai_expression_summary"].outputSchema
    assert schema is not None
    properties = schema["properties"]
    for name in ("numExperiments", "numExperimentsComplete"):
        assert properties[name] == {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "default": None,
        }
    assert properties["basedOnIncompleteData"] == {
        "anyOf": [{"type": "boolean"}, {"type": "null"}],
        "default": None,
    }


async def test_the_ai_expression_schema_names_a_summary_line_experiment() -> None:
    tools = await _list_tools()

    schema = tools["get_ai_expression_summary"].outputSchema
    assert schema is not None
    summary = schema["properties"]["summary"]["anyOf"][0]
    topic = summary["properties"]["topics"]["items"]
    line = topic["properties"]["summaries"]["items"]["properties"]
    assert line["experiment_name"] == {"default": "", "type": "string"}
    assert line["assay_type"] == {"default": "", "type": "string"}


async def test_a_summarized_gene_is_served_without_experiment_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Reporter:
        async def get_ai_expression_report(
            self, primary_keys: str
        ) -> AiExpressionReport:
            del primary_keys
            return AiExpressionReport.model_validate(
                load_recorded("ai_expression_summary_present").json_body()
            )

    monkeypatch.setattr(ai_expression, "get_wdk_client", lambda _site: _Reporter())

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "get_ai_expression_summary",
            {"site_id": SITE, "gene_id": "PF3D7_0709000"},
        )

    content = result.structured_content
    assert content is not None
    assert content["geneId"] == "PF3D7_0709000"
    assert content["resultStatus"] == "present"
    assert content["numExperiments"] is None
    assert content["numExperimentsComplete"] is None
    assert content["basedOnIncompleteData"] is False
    assert content["unavailableReason"] is None
    line = content["summary"]["topics"][0]["summaries"][0]
    assert line["experiment_name"] == (
        "Intraerythrocytic development cycle transcriptome (2018)"
    )
    assert line["assay_type"] == "RNA-Seq"


async def test_run_control_tests_on_search_declares_a_budget_over_the_default() -> None:
    tools = await _list_tools()

    meta = tools["run_control_tests_on_search"].meta
    assert meta is not None
    assert meta[MAX_CALL_SECONDS_META_KEY] > 60


async def test_a_catalog_call_answers_from_the_catalog_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def record_types(site_id: str) -> list[RecordTypeInfo]:
        assert site_id == SITE
        return [RecordTypeInfo(name="transcript", display_name="Genes", description="")]

    monkeypatch.setattr(sites, "get_record_types", record_types)

    async with _served(_service_credential()) as client:
        result = await client.call_tool("list_record_types", {"site_id": SITE})

    assert result.structured_content == {
        "result": [{"name": "transcript", "display_name": "Genes", "description": ""}]
    }


async def test_a_record_call_answers_from_the_gene_lookup_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    async def resolve(
        site_id: str,
        gene_ids: list[str],
        *,
        record_type: str,
        search_name: str,
        param_name: str,
    ) -> GeneResolveResult:
        del site_id, record_type, search_name, param_name
        seen.append(gene_ids)
        return GeneResolveResult(records=[], total_count=1)

    monkeypatch.setattr(user_tools, "resolve_gene_ids", resolve)

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "resolve_gene_ids_to_records",
            {"site_id": SITE, "gene_ids": [" PF3D7_1222600 ", "", "PF3D7_1222600"]},
        )

    assert seen == [["PF3D7_1222600"]]
    assert result.structured_content is not None
    assert result.structured_content["total_count"] == 1


async def test_a_step_call_answers_from_the_results_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Results:
        async def get_download_url(
            self,
            step_id: int,
            output_format: str = "csv",
            attributes: list[str] | None = None,
        ) -> str:
            del attributes
            return f"https://plasmodb.org/temporary-results/{step_id}.{output_format}"

    monkeypatch.setattr(step_preview, "get_results_api", lambda site_id: _Results())

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "get_step_download_url",
            {"site_id": SITE, "wdk_step_id": 42, "output_format": "tab"},
        )

    assert result.structured_content == {
        "stepId": 42,
        "format": "tab",
        "downloadUrl": "https://plasmodb.org/temporary-results/42.tab",
    }


async def test_an_evidence_call_answers_from_the_control_test_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run(
        config: Any,
        *,
        positive_controls: list[str] | None = None,
        negative_controls: list[str] | None = None,
        skip_cleanup: bool = False,
    ) -> ControlTestResult:
        del negative_controls, skip_cleanup
        assert positive_controls == ["PF3D7_1222600"]
        assert config.controls_search_name == "GeneByLocusTag"
        return ControlTestResult(site_id=config.site_id, record_type=config.record_type)

    monkeypatch.setattr(user_tools, "run_positive_negative_controls", run)

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "run_control_tests_on_search",
            {
                "site_id": SITE,
                "target_search_name": "GenesByMolecularWeight",
                "target_parameters": {},
                "positive_controls": ["PF3D7_1222600"],
            },
        )

    assert result.structured_content is not None
    assert result.structured_content["siteId"] == SITE


async def test_a_user_credential_reaches_wdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    async def record_types(site_id: str) -> list[RecordTypeInfo]:
        del site_id
        seen.append(veupathdb_auth_token_ctx.get())
        return []

    monkeypatch.setattr(sites, "get_record_types", record_types)

    async with _served(_user_credential("user-bearer")) as client:
        await client.call_tool("list_record_types", {"site_id": SITE})

    assert seen == ["user-bearer"]


async def test_a_service_credential_leaves_the_wdk_token_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    async def record_types(site_id: str) -> list[RecordTypeInfo]:
        del site_id
        seen.append(veupathdb_auth_token_ctx.get())
        return []

    monkeypatch.setattr(sites, "get_record_types", record_types)

    # A token left over from anything else must not travel with a service call.
    reset = veupathdb_auth_token_ctx.set("someone-elses-bearer")
    try:
        async with _served(_service_credential()) as client:
            await client.call_tool("list_record_types", {"site_id": SITE})
    finally:
        veupathdb_auth_token_ctx.reset(reset)

    assert seen == [None]


async def test_an_unknown_site_is_refused_naming_site_id() -> None:
    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "list_record_types", {"site_id": "nosuchdb"}, raise_on_error=False
        )

    assert result.is_error
    message = _error_text(result)
    assert "site_id" in message
    assert "nosuchdb" in message
    assert SITE in message


async def test_a_call_without_a_verified_credential_is_refused() -> None:
    async with _served(None) as client:
        result = await client.call_tool(
            "list_record_types", {"site_id": SITE}, raise_on_error=False
        )

    assert result.is_error
    assert "credential" in _error_text(result)


async def test_an_out_of_bounds_gene_list_is_refused_naming_gene_ids() -> None:
    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "resolve_gene_ids_to_records",
            {"site_id": SITE, "gene_ids": [f"GENE_{index}" for index in range(201)]},
            raise_on_error=False,
        )

    assert result.is_error
    assert "gene_ids" in _error_text(result)


async def test_a_param_spec_call_answers_from_the_search_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def inspect(
        site_id: str,
        search_name: str,
        *,
        record_type: str | None = None,
        query: str | None = None,
    ) -> SearchInspection:
        del site_id, query
        assert search_name == "GenesByMolecularWeight"
        assert record_type is None
        return SearchInspection(
            record_type="transcript",
            definition=WDKSearch(
                url_segment=search_name,
                parameters=[
                    WDKStringParam(name="min_molecular_weight", is_number=True)
                ],
            ),
            overview=SearchOverviewResult(
                search_name=search_name,
                display_name=search_name,
                description="",
                record_type="transcript",
            ),
        )

    monkeypatch.setattr(search_inspection, "inspect_search", inspect)

    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "get_search_param_specs",
            {"site_id": SITE, "search_name": "GenesByMolecularWeight"},
        )

    assert result.structured_content is not None
    specs = result.structured_content["result"]
    assert [spec["name"] for spec in specs] == ["min_molecular_weight"]


async def test_an_unknown_search_is_a_tool_error_that_names_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(
        site_id: str,
        search_name: str,
        *,
        record_type: str | None = None,
        query: str | None = None,
    ) -> SearchInspection:
        del site_id, record_type, query
        raise UnknownSearchError(search_name, ["GenesByMolecularWeight"])

    monkeypatch.setattr(search_inspection, "inspect_search", refuse)

    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "get_search_param_specs",
            {"site_id": SITE, "search_name": "GenesByMolecularWeigth"},
            raise_on_error=False,
        )

    assert result.is_error
    text = _error_text(result)
    assert text.startswith("search_name is not on this site.")
    assert "Did you mean: ['GenesByMolecularWeight']?" in text


async def test_a_validation_call_answers_from_the_validation_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, ParamValue]] = []

    async def validate(
        ctx: SearchContext,
        *,
        parameters: dict[str, ParamValue],
        callbacks: object,
    ) -> ValidatedParams:
        del callbacks
        assert ctx.site_id == SITE
        assert ctx.search_name == "GenesByText"
        seen.append(parameters)
        return ValidatedParams(params=parameters, record_class="transcript")

    monkeypatch.setattr(catalog_tools, "validate_parameters", validate)

    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "validate_search_parameters",
            {
                "site_id": SITE,
                "search_name": "GenesByText",
                "parameter_values": {
                    "text_expression": StringValue(value="kinase").model_dump(
                        mode="json"
                    )
                },
            },
        )

    assert seen == [{"text_expression": StringValue(value="kinase")}]
    assert result.structured_content is not None
    assert result.structured_content["recordClass"] == "transcript"


async def test_a_validation_refusal_is_a_tool_error_that_names_its_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(
        ctx: SearchContext,
        *,
        parameters: dict[str, ParamValue],
        callbacks: object,
    ) -> ValidatedParams:
        del ctx, parameters, callbacks
        raise ValidationError(title="Invalid", detail="organism is required")

    monkeypatch.setattr(catalog_tools, "validate_parameters", refuse)

    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "validate_search_parameters",
            {"site_id": SITE, "search_name": "GenesByTaxon", "parameter_values": {}},
            raise_on_error=False,
        )

    assert result.is_error
    assert "organism is required" in _error_text(result)


async def test_an_index_call_answers_from_the_record_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def search(index_id: str, query: str, top_k: int) -> list[IndexHit]:
        assert index_id == "catalog:plasmodb"
        assert (query, top_k) == ("kinase", 2)
        return [IndexHit(entry_id="transcript/GenesByText", similarity=0.75)]

    monkeypatch.setattr(catalog_tools, "search_index", search)

    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "search_catalog_index",
            {"site_id": SITE, "query": "kinase", "top_k": 2},
        )

    assert result.structured_content == {
        "result": [{"entry_id": "transcript/GenesByText", "similarity": 0.75}]
    }


async def test_an_unavailable_index_is_a_tool_error_that_names_the_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(index_id: str, query: str, top_k: int) -> list[IndexHit]:
        del index_id, query, top_k
        msg = "the store refused the connection"
        raise SemanticIndexUnavailableError(msg)

    monkeypatch.setattr(catalog_tools, "search_index", refuse)

    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "search_catalog_index",
            {"site_id": SITE, "query": "kinase"},
            raise_on_error=False,
        )

    assert result.is_error
    assert "index is unavailable" in _error_text(result)


async def test_a_step_gene_read_answers_from_the_strategy_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch(
        api: object, *, step_id: int, limit: int | None = None
    ) -> list[str]:
        del api
        assert (step_id, limit) == (42, 200)
        return ["PF3D7_1222600", "PF3D7_0709000"]

    monkeypatch.setattr(user_tools, "get_strategy_api", lambda site_id: site_id)
    monkeypatch.setattr(user_tools, "fetch_gene_ids_from_step", fetch)

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "get_step_gene_ids", {"site_id": SITE, "wdk_step_id": 42}
        )

    assert result.structured_content == {"result": ["PF3D7_1222600", "PF3D7_0709000"]}


async def test_a_step_past_the_gene_bound_is_refused_naming_the_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wire answer is bounded, and a step past the bound is refused by name."""

    async def fetch(
        api: object, *, step_id: int, limit: int | None = None
    ) -> list[str]:
        del api, step_id
        assert limit == 200
        return [f"PF3D7_{index:06d}" for index in range(limit + 1)]

    monkeypatch.setattr(user_tools, "get_strategy_api", lambda site_id: site_id)
    monkeypatch.setattr(user_tools, "fetch_gene_ids_from_step", fetch)

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "get_step_gene_ids",
            {"site_id": SITE, "wdk_step_id": 42},
            raise_on_error=False,
        )

    assert result.is_error
    text = _error_text(result)
    assert "200" in text
    assert "get_step_download_url" in text


async def test_a_step_control_run_answers_from_the_control_test_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run(
        site_id: str,
        wdk_step_id: int,
        positive_controls: list[str] | None = None,
        negative_controls: list[str] | None = None,
    ) -> ControlTestResult:
        del negative_controls
        assert (site_id, wdk_step_id) == (SITE, 42)
        assert positive_controls == ["PF3D7_1222600"]
        return ControlTestResult(site_id=site_id, record_type="transcript")

    monkeypatch.setattr(user_tools, "run_step_control_tests", run)

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "run_control_tests_on_step",
            {
                "site_id": SITE,
                "wdk_step_id": 42,
                "positive_controls": [" PF3D7_1222600 "],
            },
        )

    assert result.structured_content is not None
    assert result.structured_content["siteId"] == SITE


async def test_a_step_control_run_without_a_control_is_refused() -> None:
    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "run_control_tests_on_step",
            {"site_id": SITE, "wdk_step_id": 42},
            raise_on_error=False,
        )

    assert result.is_error
    assert "positive_controls" in _error_text(result)


async def test_a_plan_count_call_answers_from_the_plan_count_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def counts(
        payload: StrategyAst,
        site_id: str,
        *,
        strategy_name: str,
    ) -> dict[str, int | None]:
        del site_id
        seen.append(strategy_name)
        return {step.id: None for step in [payload.root]} | {"g1": 132}

    monkeypatch.setattr(user_tools, "compute_plan_step_counts", counts)

    plan = StrategyAst(
        record_type="transcript",
        root=StrategyStepNode(id="g1", search_name="GenesByText"),
    )
    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "count_plan_steps",
            {"site_id": SITE, "plan": plan.model_dump(by_alias=True, mode="json")},
        )

    assert seen == ["step counts"]
    assert result.structured_content == {"g1": 132}


async def test_a_gene_set_step_call_answers_from_the_frozen_step_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    async def frozen(
        site_id: str,
        gene_ids: list[str],
        record_type: str,
        *,
        strategy_name: str,
    ) -> int | None:
        del site_id, record_type
        assert strategy_name == "gene set"
        seen.append(gene_ids)
        return 4242

    monkeypatch.setattr(user_tools, "frozen_step_id", frozen)

    async with _served(_user_credential("user-bearer")) as client:
        result = await client.call_tool(
            "create_gene_set_step",
            {"site_id": SITE, "gene_ids": [" PF3D7_1222600 ", "PF3D7_1222600"]},
        )

    assert seen == [["PF3D7_1222600"]]
    assert result.structured_content == {"result": 4242}


class _FakeStepApi:
    """The WDK step and strategy writes a frozen gene set step makes."""

    def __init__(self, first_id: int) -> None:
        self.next_id = first_id

    async def create_step(self, spec: NewStepSpec, record_type: str) -> WDKIdentifier:
        del spec, record_type
        self.next_id += 1
        return WDKIdentifier(id=self.next_id)

    async def create_strategy(
        self,
        step_tree: WDKStepTree,
        name: str,
        description: str | None = None,
        **kwargs: Any,
    ) -> WDKIdentifier:
        del step_tree, name, description, kwargs
        return WDKIdentifier(id=9000)


async def test_two_bearers_with_the_same_genes_get_two_gene_set_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step id names a step in one account, so no caller reads another's step."""
    api = _FakeStepApi(600)

    async def params(
        site_id: str, gene_ids: list[str]
    ) -> tuple[str, dict[str, ParamValue], str]:
        del site_id, gene_ids
        return (
            "GeneByLocusTag",
            {"ds_gene_ids": InputDatasetValue(dataset_id="ds-1")},
            "transcript",
        )

    gene_set_steps._FROZEN_STEPS.clear()
    monkeypatch.setattr(gene_set_steps, "get_strategy_api", lambda site_id: api)
    monkeypatch.setattr(gene_set_steps, "build_enrichment_params_from_gene_ids", params)

    arguments = {"site_id": SITE, "gene_ids": ["PF3D7_1222600"]}
    async with _served(_user_credential("alice-bearer", "alice@example.org")) as client:
        alice = await client.call_tool("create_gene_set_step", arguments)
        again = await client.call_tool("create_gene_set_step", arguments)
    async with _served(_user_credential("bob-bearer", "bob@example.org")) as client:
        bob = await client.call_tool("create_gene_set_step", arguments)

    assert alice.structured_content == {"result": 601}
    assert again.structured_content == {"result": 601}
    assert bob.structured_content == {"result": 602}


async def test_a_binding_call_answers_from_the_parameter_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, dict[str, str | list[str]] | None]] = []

    async def resolve(
        *,
        fetch_at: object,
        intent: ParamIntent,
        overrides: dict[str, str | list[str]] | None = None,
    ) -> ResolvedParams:
        del fetch_at
        seen.append((intent.text, overrides))
        return ResolvedParams(params={"organism": StringValue(value="P. falciparum")})

    monkeypatch.setattr(catalog_tools, "resolve_params_with_intent", resolve)

    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "resolve_search_parameters",
            {
                "site_id": SITE,
                "search_name": "GenesByTaxon",
                "criterion": "falciparum genes",
                "overrides": {"organism": "P. falciparum"},
            },
        )

    assert seen == [("falciparum genes", {"organism": "P. falciparum"})]
    assert result.structured_content is not None
    assert result.structured_content["openSlots"] == []


async def test_an_override_that_names_no_parameter_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(
        *,
        fetch_at: object,
        intent: ParamIntent,
        overrides: dict[str, str | list[str]] | None = None,
    ) -> ResolvedParams:
        del fetch_at, intent, overrides
        raise UnknownParameterError(["orgnism"], ["organism"])

    monkeypatch.setattr(catalog_tools, "resolve_params_with_intent", refuse)

    async with _served(_service_credential()) as client:
        result = await client.call_tool(
            "resolve_search_parameters",
            {
                "site_id": SITE,
                "search_name": "GenesByTaxon",
                "overrides": {"orgnism": "P. falciparum"},
            },
            raise_on_error=False,
        )

    assert result.is_error
    assert _error_text(result) == (
        "No such parameter(s) on this search: ['orgnism']. Valid names: ['organism']."
    )
