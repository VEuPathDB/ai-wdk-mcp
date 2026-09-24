"""The MCP server configures its own process logging."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from veupathdb_mcp.logging_setup import setup_logging


def test_the_server_renders_its_log_as_json(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    setup_logging()
    structlog.get_logger("veupathdb-wdk-mcp").info("served", site_id="plasmodb")

    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "served"
    assert line["site_id"] == "plasmodb"
    assert line["level"] == "info"


def test_the_server_lets_the_request_lines_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uvicorn ships with propagate off, so its access lines need it flipped."""
    monkeypatch.setenv("LOG_FORMAT", "json")

    setup_logging()

    assert logging.getLogger("uvicorn.access").propagate is True
    assert logging.getLogger("httpx").level == logging.WARNING
