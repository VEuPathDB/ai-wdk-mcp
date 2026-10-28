"""A Decisions transport for a suite that makes no network call."""

from veupathdb_mcp.catalog.decisions import DecisionRequest, DecisionResponse


async def offline_decisions(request: DecisionRequest) -> DecisionResponse | None:
    """Answer no request, as the service does when it is unreachable."""
    del request
    return None
