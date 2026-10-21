"""A rate over the calls checked, with its Wilson 95% interval, and its floor and
ceiling over every call when some calls could not be checked."""

from __future__ import annotations

import math
from typing import Self

from pydantic import ConfigDict, Field, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.computed import computed

WILSON_Z = 1.959963984540054


class RateBounds(CamelModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmed: int = Field(ge=0)
    checked: int = Field(ge=0)
    unresolved: int = Field(ge=0)

    @model_validator(mode="after")
    def _confirmed_among_checked(self) -> Self:
        if self.confirmed > self.checked:
            msg = f"{self.confirmed} confirmed calls exceed the {self.checked} checked"
            raise ValueError(msg)
        return self

    def _wilson_low(self, confirmed: int) -> float:
        squared = WILSON_Z * WILSON_Z
        spread = WILSON_Z * math.sqrt(
            confirmed * (self.checked - confirmed) / self.checked + squared / 4
        )
        return (confirmed + squared / 2 - spread) / (self.checked + squared)

    def _over_all(self, count: int, empty: float) -> float:
        total = self.checked + self.unresolved
        return count / total if total else empty

    @computed
    def rate(self) -> float:
        return self.confirmed / self.checked if self.checked else 0.0

    @computed
    def low(self) -> float:
        return self._wilson_low(self.confirmed) if self.checked else 0.0

    @computed
    def high(self) -> float:
        if not self.checked:
            return 1.0
        return 1 - self._wilson_low(self.checked - self.confirmed)

    @computed
    def floor(self) -> float:
        return self._over_all(self.confirmed, 0.0)

    @computed
    def ceiling(self) -> float:
        return self._over_all(self.confirmed + self.unresolved, 1.0)


def rate_with_bounds(confirmed: int, checked: int, unresolved: int) -> RateBounds:
    return RateBounds(confirmed=confirmed, checked=checked, unresolved=unresolved)
