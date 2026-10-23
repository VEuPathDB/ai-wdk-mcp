from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict

SITE_LIMITS_FILE = "orthomcl_phyletic_site_limits.json"
SITE_LIMITS = files("veupathdb_mcp.catalog") / "data" / SITE_LIMITS_FILE
SECONDS_PER_PROBE = 0.3
ANSWERED = 200


class _Measured(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    characters: int
    seconds: float
    status: int


class _SiteLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    measured: tuple[_Measured, ...]


@dataclass(frozen=True, slots=True)
class SiteCost:
    fixed: float
    per_character: float
    longest: int

    def seconds(self, characters: int, probes: int) -> float:
        return self.fixed + self.per_character * characters + SECONDS_PER_PROBE * probes

    def reads_within(self, budget: float) -> int:
        spare = budget - self.seconds(self.longest, 0)
        return max(int(spare / SECONDS_PER_PROBE), 0)

    def characters_within(self, budget: float, probes: int) -> int:
        spare = budget - self.fixed - SECONDS_PER_PROBE * probes
        return max(int(spare / self.per_character), 0)


def fit(rows: tuple[tuple[int, float], ...]) -> SiteCost:
    weights = [1 / seconds**2 for _, seconds in rows]
    total = sum(weights)
    mean_x = sum(w * x for w, (x, _) in zip(weights, rows, strict=True)) / total
    mean_y = sum(w * y for w, (_, y) in zip(weights, rows, strict=True)) / total
    spread = sum(w * (x - mean_x) ** 2 for w, (x, _) in zip(weights, rows, strict=True))
    shared = sum(
        w * (x - mean_x) * (y - mean_y) for w, (x, y) in zip(weights, rows, strict=True)
    )
    per_character = shared / spread
    return SiteCost(
        fixed=mean_y - per_character * mean_x,
        per_character=per_character,
        longest=max(characters for characters, _ in rows),
    )


def measured_rows() -> tuple[tuple[int, float], ...]:
    recording = _SiteLimits.model_validate_json(SITE_LIMITS.read_text())
    return tuple(
        (row.characters, row.seconds)
        for row in recording.measured
        if row.status == ANSWERED
    )


@cache
def site_cost() -> SiteCost:
    return fit(measured_rows())
