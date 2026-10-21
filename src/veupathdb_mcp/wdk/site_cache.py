"""A value read once per site in a process."""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class SiteCache[T]:
    def __init__(self) -> None:
        self._held: dict[str, T] = {}

    async def read(self, site_id: str, fresh: Callable[[str], Awaitable[T]]) -> T:
        if site_id not in self._held:
            self._held[site_id] = await fresh(site_id)
        return self._held[site_id]
