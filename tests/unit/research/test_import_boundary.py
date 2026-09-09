"""The research process serves the open web, and carries nothing of the WDK server."""

from __future__ import annotations

import subprocess
import sys

import pytest


def _probe_output(finished: subprocess.CompletedProcess[str]) -> str:
    if finished.returncode != 0:
        pytest.fail(finished.stderr)
    return finished.stdout.strip()


def test_the_research_entrypoint_loads_no_wdk_module() -> None:
    """A fresh interpreter proves the split, which an already-imported one cannot."""
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import veupathdb_mcp.research.__main__

wdk_only = (
    "veupathdb_mcp.server",
    "veupathdb_mcp.catalog",
    "veupathdb_mcp.embeddings",
    "veupathdb_mcp.wdk",
)
print(sorted(name for name in sys.modules if name.startswith(wdk_only)))
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert _probe_output(probe) == "[]"


def test_the_research_entrypoint_opens_no_database_package() -> None:
    """It reads no embedding index, so it loads neither a driver nor an ORM."""
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import veupathdb_mcp.research.__main__

roots = {name.split(".")[0] for name in sys.modules}
print(sorted(roots & {"sqlalchemy", "asyncpg", "pgvector"}))
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert _probe_output(probe) == "[]"
