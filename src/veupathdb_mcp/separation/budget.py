"""The WDK requests a separation run may make, and what each stage is charged.

Each charge is the count of HTTP requests the stage made on plasmodb, recorded
in ``tests/unit/separation/fixtures/one_run_requests.json``.
"""

from dataclasses import dataclass

MAX_CRITERIA = 6
"""The most leaves one assembled tree holds."""

RESOLVE_REQUESTS = 4
"""One id resolution: the session, the user read, the dataset and the report."""

CLEANUP_REQUESTS = 3
"""The session, the user read, and the list of the account's strategies."""

UPLOAD_REQUESTS = 2
"""The controls parameter-type read and the one dataset of every control."""

MEASURE_REQUESTS = 10
"""Three steps and the read each makes of its search, the strategy, the count,
the answer and the delete."""

SEARCH_READ_REQUESTS = 1
"""One read of a search: its definition, first read by the catalog or by the
first step of it, or its parameters under a context."""

FIRST_INTERSECTION_REQUESTS = 2
"""The second read of the controls search and the search listing, once a run."""

ENRICHMENT_REQUESTS = 34
"""One by-value enrichment of the GO and pathway analyses a run asks for.

Each analysis polls its status, so a slow site answers with more requests.
"""


def confirm_requests(leaves: int) -> int:
    """The requests that build and read an assembled tree of ``leaves`` criteria.

    Each leaf and each combine is a step and a read of its search; then the
    controls step, its combine, the strategy, the count, the answer and the delete.
    """
    return 4 * leaves + 6


CONFIRM_RESERVATION = confirm_requests(MAX_CRITERIA)
"""The requests a run holds back, before any other charge, to read its largest tree."""


class BudgetSpentError(Exception):
    """A charge the budget cannot afford."""

    def __init__(self, requests: int, budget: "WdkCallBudget") -> None:
        self.requests = requests
        super().__init__(
            f"{requests} WDK requests exceed the budget: {budget.spent} charged and "
            f"{budget.reserved} reserved of {budget.limit}"
        )


@dataclass
class WdkCallBudget:
    """The WDK requests a run may make, charged at each call site before the call.

    The unit is an estimate of requests: each charge is the count its stage made
    on the recorded run. A reservation holds requests back for a later stage.
    """

    limit: int
    spent: int = 0
    reserved: int = 0

    def affords(self, requests: int) -> bool:
        """Whether ``requests`` more fit beside what is charged and reserved."""
        return self.spent + self.reserved + requests <= self.limit

    def charge(self, requests: int) -> None:
        """Charge ``requests``, or raise ``BudgetSpentError`` when they do not fit."""
        if not self.affords(requests):
            raise BudgetSpentError(requests, self)
        self.spent += requests

    def reserve(self, requests: int) -> None:
        """Hold ``requests`` back for a later stage."""
        if not self.affords(requests):
            raise BudgetSpentError(requests, self)
        self.reserved += requests

    def release(self) -> None:
        """Return the reservation, so the stage it was held for can charge it."""
        self.reserved = 0

    def measurements_left(self) -> int:
        """The candidate measurements the unreserved requests still pay for."""
        return (self.limit - self.spent - self.reserved) // MEASURE_REQUESTS
