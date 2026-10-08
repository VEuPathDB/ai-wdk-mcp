"""Each image is the last stage of its own file, over one install stage."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent

SERVED = {
    "Dockerfile": "veupathdb_mcp",
    "Dockerfile.research": "veupathdb_mcp.research",
}


def _stages(name: str) -> list[str]:
    return (ROOT / name).read_text().split("\nFROM ")


def test_both_files_share_one_install_stage() -> None:
    wdk, research = (_stages(name)[:-1] for name in SERVED)

    assert wdk == research


@pytest.mark.parametrize("name", SERVED)
def test_the_last_stage_builds_on_the_install_stage(name: str) -> None:
    assert _stages(name)[-1].startswith("base AS ")


@pytest.mark.parametrize(("name", "module"), SERVED.items())
def test_the_last_stage_serves_its_module(name: str, module: str) -> None:
    """A builder that takes no target builds the last stage of the file."""
    commands = [
        line for line in _stages(name)[-1].splitlines() if line.startswith("CMD ")
    ]

    assert commands == [f'CMD [".venv/bin/python", "-m", "{module}"]']
