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
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk.ai_expression import AiExpressionReport

from veupathdb_mcp import server
from veupathdb_mcp.auth import CredentialMode, McpCredential
from veupathdb_mcp.catalog import sites
from veupathdb_mcp.catalog.models import RecordTypeInfo
from veupathdb_mcp.controls.control_types import ControlTestResult
from veupathdb_mcp.gene_lookup import GeneResolveResult
from veupathdb_mcp.tool_meta import (
    MAX_CALL_SECONDS_META_KEY,
    STREAM_PART_META_KEY,
)
from veupathdb_mcp.tools import user_tools
from veupathdb_mcp.wdk import ai_expression, step_preview

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


def _user_credential(token: str) -> McpCredential:
    return McpCredential(
        token=token,
        client_id="researcher@example.org",
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


async def test_the_served_inventory_is_the_published_seventeen() -> None:
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
