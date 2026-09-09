"""What the research server declares about its two tools."""

from __future__ import annotations

from veupathdb_mcp.research.server import (
    SOURCES_PART_KIND,
    TOOLS,
    build_server,
)

DECLARED = {
    "org.veupathdb.assistant/streamPart": {
        "kind": "data-research.sources",
        "version": 1,
    },
    "org.veupathdb.assistant/maxCallSeconds": 60,
}


def test_both_tools_read_the_open_web() -> None:
    """The WDK server closes this hint; a tool that reaches the web opens it."""
    hints = [
        (row.annotations.readOnlyHint, row.annotations.openWorldHint) for row in TOOLS
    ]

    assert hints == [(True, True), (True, True)]


def test_every_tool_declares_the_sources_part_and_the_call_budget() -> None:
    declared = [row.meta for row in TOOLS]

    assert declared == [DECLARED, DECLARED]


def test_the_declared_part_sits_in_the_research_namespace() -> None:
    """A source's records are refused when a part leaves its own namespace."""
    assert SOURCES_PART_KIND == "data-research.sources"


def test_no_tool_names_a_site() -> None:
    """These tools reach the open web, so the site guard has nothing to check."""
    named = [row.fn.__name__ for row in TOOLS if "site_id" in row.fn.__annotations__]

    assert named == []


async def test_the_served_input_schema_names_one_vocabulary() -> None:
    """A tool's arguments are snake_case, nested arguments included."""
    tool = await build_server().get_tool("literature_search")
    schema = tool.parameters

    assert list(schema["properties"]) == [
        "query",
        "limit",
        "sort",
        "source",
        "output_options",
        "filters",
    ]
    assert list(schema["$defs"]["LiteratureFilters"]["properties"]) == [
        "year_from",
        "year_to",
        "author_includes",
        "title_includes",
        "journal_includes",
        "doi_equals",
        "pmid_equals",
        "require_doi",
    ]
    assert list(schema["$defs"]["LiteratureOutputOptions"]["properties"]) == [
        "include_abstract",
        "abstract_max_chars",
        "max_authors",
    ]
