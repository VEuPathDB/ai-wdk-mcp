"""Wire labels for enrichment values that can be None.

A None ratio is unbounded. A None probability is not computable.
"""

UNBOUNDED_RATIO_LABEL = "Inf"


def ratio_cell(value: float | None) -> str | float:
    """Render a ratio for a file or a JSON matrix."""
    return UNBOUNDED_RATIO_LABEL if value is None else round(value, 4)


def probability_cell(value: float | None) -> str | float:
    """Render a probability for a file or a JSON matrix."""
    return "" if value is None else value
