from __future__ import annotations

from fastmcp import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.types import TextContent
from tests._support.column_site import STEP, ColumnSite, column_site

from veupathdb_mcp import server
from veupathdb_mcp.auth import CredentialMode, McpCredential

__all__ = ["column_site"]

SITE = "plasmodb"
RESEARCHER = McpCredential(
    token="user-bearer",
    client_id="researcher@example.org",
    scopes=[],
    mode=CredentialMode.VEUPATHDB_USER,
)


async def _call(name: str, arguments: dict[str, object]) -> tuple[bool, object, str]:
    reset = auth_context_var.set(AuthenticatedUser(RESEARCHER))
    try:
        async with Client(server.build_server()) as client:
            result = await client.call_tool(name, arguments, raise_on_error=False)
    finally:
        auth_context_var.reset(reset)
    text = " ".join(
        block.text for block in result.content if isinstance(block, TextContent)
    )
    return result.is_error, result.structured_content, text


async def test_a_served_count_answers_the_ranked_values_in_camel_case(
    column_site: ColumnSite,
) -> None:
    failed, content, _ = await _call(
        "count_step_by_column",
        {"site_id": SITE, "wdk_step_id": STEP, "column": "organism", "top": 1},
    )

    assert not failed
    assert content == {
        "stepId": STEP,
        "column": "organism",
        "displayName": "Organism",
        "kind": "string",
        "totalRecords": 797,
        "distinctValues": 5,
        "values": [{"value": "Plasmodium falciparum 3D7", "count": 310}],
        "bins": [],
        "statistics": None,
    }
    assert column_site.posts() == [
        f"POST /users/42/steps/{STEP}/columns/organism/reports/byValue"
    ]


async def test_a_served_count_of_an_unknown_column_names_the_countable_ones(
    column_site: ColumnSite,
) -> None:
    failed, _, text = await _call(
        "count_step_by_column",
        {"site_id": SITE, "wdk_step_id": STEP, "column": "taxon_name"},
    )

    assert failed
    assert "exon_count, gene_product, organism, primary_key" in text
    assert "get_step_columns" in text
    assert column_site.posts() == []


async def test_a_served_count_refuses_a_top_past_its_bound_before_a_request(
    column_site: ColumnSite,
) -> None:
    failed, _, _ = await _call(
        "count_step_by_column",
        {"site_id": SITE, "wdk_step_id": STEP, "column": "organism", "top": 201},
    )

    assert failed
    assert column_site.requests == []


async def test_the_served_columns_say_which_can_be_counted(
    column_site: ColumnSite,
) -> None:
    failed, content, _ = await _call(
        "get_step_columns", {"site_id": SITE, "wdk_step_id": STEP}
    )

    assert not failed
    assert content is not None
    assert content["recordType"] == "transcript"
    assert [
        (column["name"], column["dataType"], column["countable"])
        for column in content["columns"]
    ][-3:] == [
        ("overview", "OTHER", False),
        ("matched_result", "STRING", False),
        ("wdk_weight", "NUMBER", False),
    ]
    assert column_site.posts() == []


async def test_the_count_description_says_how_to_choose_a_column() -> None:
    async with Client(server.build_server()) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    description = tools["count_step_by_column"].description or ""
    assert "get_step_columns" in description
    assert "transform" in description
