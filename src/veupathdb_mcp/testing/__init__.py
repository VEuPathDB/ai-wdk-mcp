"""What a suite reads of this distribution.

The OrthoMCL count recordings, and a Decisions transport with no network.
"""

from veupathdb_mcp.testing.decisions import offline_decisions
from veupathdb_mcp.testing.fixture_store import (
    FIXTURE_ROOT,
    ORTHOMCL_COUNTS,
    ORTHOMCL_GROUP_CLOUDS,
)

__all__ = [
    "FIXTURE_ROOT",
    "ORTHOMCL_COUNTS",
    "ORTHOMCL_GROUP_CLOUDS",
    "offline_decisions",
]
