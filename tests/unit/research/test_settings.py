"""The research server reads its own variables, and none of the WDK server's."""

from __future__ import annotations

import pytest

from veupathdb_mcp.research.settings import ResearchSettings
from veupathdb_mcp.settings import McpSettings

SECRET = "research-mcp-service-secret-0123456789ab"


def test_every_variable_carries_the_research_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_MCP_BASE_URL", "https://research-mcp.test")
    monkeypatch.setenv("RESEARCH_MCP_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("RESEARCH_MCP_MAX_RETRIES", "5")

    settings = ResearchSettings()

    assert (settings.base_url, settings.timeout_seconds, settings.max_retries) == (
        "https://research-mcp.test",
        30.0,
        5,
    )


def test_the_wdk_service_tokens_do_not_admit_a_research_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two servers, two secrets: one deployment may run only one of them."""
    monkeypatch.setenv("PATHFINDER_MCP_SERVICE_TOKENS", f"gene-page:{SECRET}")

    assert ResearchSettings().research_service_tokens.tokens == ()
    assert McpSettings().mcp_service_tokens.application_for(SECRET) == "gene-page"


def test_a_configured_application_is_named_by_its_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_MCP_SERVICE_TOKENS", f"pathfinder:{SECRET}")

    assert ResearchSettings().research_service_tokens.application_for(SECRET) == (
        "pathfinder"
    )


def test_the_crossref_mailbox_is_empty_until_a_deployment_names_one() -> None:
    assert ResearchSettings().crossref_mailto == ""
