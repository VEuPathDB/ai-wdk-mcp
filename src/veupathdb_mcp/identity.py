"""Who a VEuPathDB bearer names, read from the token and nothing else."""

from __future__ import annotations

import hashlib
import time

from veupathdb import get_veupathdb_settings
from veupathdb.wdk import validate_oauth_token

_SUBJECT_CACHE_SECONDS = 300.0
_SUBJECT_CACHE_MAX_ENTRIES = 512

_subjects: dict[str, tuple[float, str]] = {}


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def resolve_oauth_subject(token: str) -> str | None:
    """The registered VEuPathDB subject the token names, or None.

    The signature is verified against the OAuth server's cached key, so a
    forged or expired token names nobody, and a guest token names nobody
    durable. The answer is remembered per token for a few minutes.
    """
    key = _key(token)
    cached = _subjects.get(key)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]

    claims = await validate_oauth_token(
        token, get_veupathdb_settings().veupathdb_oauth_url
    )
    if claims is None or claims.is_guest:
        return None

    if len(_subjects) >= _SUBJECT_CACHE_MAX_ENTRIES:
        _subjects.clear()
    _subjects[key] = (time.monotonic() + _SUBJECT_CACHE_SECONDS, claims.sub)
    return claims.sub
