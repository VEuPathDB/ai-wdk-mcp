"""The searches a Decisions choice over every offered search picks for a query.

The offered searches are split into even chunks of at most 255, one choice
question per chunk, in one request. The top three of each chunk that the choice gives any weight are the picks.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from veupathdb import strip_html_tags
from veupathdb.wdk import WDKSearch

from veupathdb_mcp.catalog.decisions import (
    MAX_CHOICES,
    Choice,
    ChoiceQuestion,
    DecisionRequest,
    decide,
)
from veupathdb_mcp.catalog.models import SearchMatch

PICKS_PER_CHUNK = 3
# A pick below this probability added no recall on the measured set.
MIN_PICK_PROBABILITY = 0.01
_FEWEST_CHOICES = 2
_DESCRIPTION_CHARS = 60
_INSTRUCTIONS = "Which of these searches, if any, states the requirement?"


def _choice(search: WDKSearch) -> Choice:
    text = strip_html_tags(search.summary or search.description)
    display = search.display_name or search.url_segment
    return Choice(
        value=search.url_segment,
        description=f"{display}: {text[:_DESCRIPTION_CHARS]}",
    )


def catalog_choice_request(
    site_id: str,
    record_types: Sequence[str],
    query: str,
    offered: Sequence[WDKSearch],
) -> DecisionRequest | None:
    """One choice question per even chunk of the offered searches."""
    unique = list({s.url_segment: s for s in offered}.values())
    if len(unique) < _FEWEST_CHOICES:
        return None
    chunks = math.ceil(len(unique) / MAX_CHOICES)
    size = math.ceil(len(unique) / chunks)
    return DecisionRequest(
        input=(
            f"VEuPathDB site: {site_id}. Record types: {', '.join(record_types)}.\n"
            f"Requirement to find a search for: {query}"
        ),
        questions=[
            ChoiceQuestion(
                name=f"chunk{i}",
                instructions=_INSTRUCTIONS,
                choices=[_choice(s) for s in unique[start : start + size]],
            )
            for i, start in enumerate(range(0, len(unique), size))
        ],
    )


async def decision_picks(
    site_id: str,
    record_types: Sequence[str],
    query: str,
    offered: Sequence[WDKSearch],
) -> dict[str, float]:
    """Each picked search name with its probability, or none when the service is off."""
    request = catalog_choice_request(site_id, record_types, query, offered)
    if request is None or not query.strip():
        return {}
    response = await decide(request, purpose="search candidates")
    if response is None:
        return {}
    picks: dict[str, float] = {}
    for question in request.questions:
        answer = response.choice(question.name)
        if answer is None:
            continue
        for ranked in answer.ranked()[:PICKS_PER_CHUNK]:
            if ranked.probability >= MIN_PICK_PROBABILITY:
                picks[ranked.value] = ranked.probability
    return picks


def with_decision_picks(
    ranked: list[SearchMatch],
    scored: Sequence[tuple[float, SearchMatch]],
    picks: dict[str, float],
) -> list[SearchMatch]:
    """The ranking as it stands, each pick marked, and the picks it lacks after it."""
    shown = {match.name for match in ranked}
    marked = [
        replace(match, decision_probability=picks[match.name])
        if match.name in picks
        else match
        for match in ranked
    ]
    entries = {entry.name: entry for _, entry in scored}
    added = [
        replace(entries[name], decision_probability=probability)
        for name, probability in sorted(picks.items(), key=lambda p: -p[1])
        if name not in shown and name in entries
    ]
    return marked + added
