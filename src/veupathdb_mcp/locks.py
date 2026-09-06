"""One asyncio lock per key, for work that must not run twice at once."""

from __future__ import annotations

import asyncio


class KeyedLock:
    """Hands out one lock per key, created on first use.

    The keys are a closed set (site ids), so the locks are never discarded: a
    lock dropped while a caller holds it would stop excluding anything.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def __call__(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock
