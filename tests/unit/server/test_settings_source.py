"""The MCP server reads the host's settings, and never computes a config path."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from veupathdb_mcp.service_tokens import ServiceTokenRegistry
from veupathdb_mcp.settings import (
    McpSettings,
    get_mcp_settings,
    use_mcp_settings_source,
)

SECRET = "wdk-mcp-service-secret-0123456789ab"


def test_the_installed_source_serves_the_server() -> None:
    settings = McpSettings(wdk_mcp_base_url="https://wdk-mcp.test")
    use_mcp_settings_source(lambda: settings)

    assert get_mcp_settings() is settings


def test_the_server_settings_keep_the_environment_variable_names() -> None:
    assert set(McpSettings.model_fields) == {
        "catalog_cache_dir",
        "catalog_refresh_enabled",
        "embedding_index_sync_enabled",
        "wdk_mcp_base_url",
        "wdk_mcp_service_tokens",
        "site_catalog_budget_mb",
    }


def test_the_server_names_its_own_settings_after_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WDK_MCP_BASE_URL", "https://wdk-mcp.test")
    monkeypatch.setenv("WDK_MCP_SERVICE_TOKENS", f"gene-page:{SECRET}")

    settings = McpSettings()

    assert settings.wdk_mcp_base_url == "https://wdk-mcp.test"
    assert settings.mcp_service_tokens.application_for(SECRET) == "gene-page"


def test_a_variable_named_after_one_host_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each setting answers to one name, and that name states no application."""
    monkeypatch.delenv("WDK_MCP_BASE_URL", raising=False)
    monkeypatch.delenv("WDK_MCP_SERVICE_TOKENS", raising=False)
    monkeypatch.setenv("PATHFINDER_MCP_BASE_URL", "https://wdk-mcp.test")
    monkeypatch.setenv("PATHFINDER_MCP_SERVICE_TOKENS", f"gene-page:{SECRET}")

    settings = McpSettings()

    assert settings.wdk_mcp_base_url == ""
    assert settings.mcp_service_tokens.tokens == ()


def test_the_server_settings_module_computes_no_path() -> None:
    spec = importlib.util.find_spec("veupathdb_mcp.settings")
    assert spec is not None
    assert spec.origin is not None
    source = Path(spec.origin).read_text()

    assert "__file__" not in source
    assert "config.toml" not in source


def test_the_served_applications_are_parsed_from_the_setting() -> None:
    settings = McpSettings(wdk_mcp_service_tokens=f"gene-page:{SECRET}")

    assert settings.mcp_service_tokens == ServiceTokenRegistry.parse(
        f"gene-page:{SECRET}"
    )
    assert settings.mcp_service_tokens.application_for(SECRET) == "gene-page"
