"""The MCP server reads the host's settings, and never computes a config path."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from veupathdb_mcp.service_tokens import ServiceTokenRegistry
from veupathdb_mcp.settings import (
    McpSettings,
    get_mcp_settings,
    use_mcp_settings_source,
)

SECRET = "wdk-mcp-service-secret-0123456789ab"


def test_the_installed_source_serves_the_server() -> None:
    settings = McpSettings(pathfinder_mcp_base_url="https://wdk-mcp.test")
    use_mcp_settings_source(lambda: settings)

    assert get_mcp_settings() is settings


def test_the_server_settings_keep_the_environment_variable_names() -> None:
    assert set(McpSettings.model_fields) == {
        "catalog_cache_dir",
        "catalog_refresh_enabled",
        "embedding_index_sync_enabled",
        "pathfinder_mcp_base_url",
        "pathfinder_mcp_service_tokens",
        "site_catalog_budget_mb",
        "veupathdb_oauth_url",
    }


def test_the_server_settings_module_computes_no_path() -> None:
    spec = importlib.util.find_spec("veupathdb_mcp.settings")
    assert spec is not None
    assert spec.origin is not None
    source = Path(spec.origin).read_text()

    assert "__file__" not in source
    assert "config.toml" not in source


def test_the_served_applications_are_parsed_from_the_setting() -> None:
    settings = McpSettings(pathfinder_mcp_service_tokens=f"gene-page:{SECRET}")

    assert settings.mcp_service_tokens == ServiceTokenRegistry.parse(
        f"gene-page:{SECRET}"
    )
    assert settings.mcp_service_tokens.application_for(SECRET) == "gene-page"
