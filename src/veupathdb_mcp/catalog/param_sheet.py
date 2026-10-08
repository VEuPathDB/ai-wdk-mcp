"""The parameter sheet a model reads before it proposes values for a search."""

from __future__ import annotations

from pydantic import Field
from veupathdb.domain.parameters import VocabOption
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.param_formatting import (
    FilterFieldInfo,
    ParameterInfo,
    shown_facets,
)
from veupathdb_mcp.catalog.shortlist import shortlist


class SheetEntry(CamelModel):
    """One parameter with everything needed to propose a value for it.

    ``hidden`` marks a parameter the site does not show but that takes any
    entry of its vocabulary.
    """

    name: str
    display_name: str
    type: str
    required: bool
    hidden: bool = False
    is_number: bool = False
    organism_param: bool = False
    is_tree: bool = False
    help: str = ""
    default: str | None = None
    min: float | None = None
    max: float | None = None
    depends_on: list[str] = Field(default_factory=list)
    vocabulary: list[VocabOption] = Field(default_factory=list)
    vocabulary_total: int = 0
    vocabulary_note: str | None = None
    filter_facets: list[FilterFieldInfo] = Field(default_factory=list)


def _note(
    info: ParameterInfo, shown: int, total: int, facets: list[FilterFieldInfo]
) -> str | None:
    parts: list[str] = []
    # An empty vocabulary offers nothing, so its note is the reason it is empty.
    if not shown and info.allowed_values_note:
        parts.append(info.allowed_values_note)
    if total > shown:
        parts.append(
            f"{total} values; the {shown} most relevant to the request by name are "
            f"shown. If the value you need is absent, call get_parameter_options("
            f"search_name, '{info.name}', query='<keyword>') before deciding it does not exist."
        )
    cut = [f.display for f in facets if f.values_total is not None]
    if cut:
        parts.append(
            f"Facets {', '.join(cut)} show part of their values; call "
            f"get_parameter_options(search_name, '{info.name}', query='<keyword>') "
            f"to read the rest."
        )
    if info.allowed_values_tree is not None:
        parts.append("A parent term selects all of its children.")
    if info.vocab_depends_on:
        parents = ", ".join(info.vocab_depends_on)
        parts.append(
            f"This vocabulary depends on {parents} and is shown under the search defaults; "
            f"it is re-read under the values you propose."
        )
    return " ".join(parts) or None


def build_sheet(infos: list[ParameterInfo], *, query: str) -> list[SheetEntry]:
    """Every parameter a value can be proposed for. A vocabulary over
    ``DIRECT_MAX`` is shortlisted.

    A hidden parameter is listed when it has a vocabulary; without one, only the
    site sets it.
    """
    entries: list[SheetEntry] = []
    for info in infos:
        options = info.vocabulary()
        if not info.is_visible and not options:
            continue
        shown = shortlist(options, query)
        facets = shown_facets(info.facets(), query)
        entries.append(
            SheetEntry(
                name=info.name,
                display_name=info.display_name,
                type=info.type,
                required=info.required,
                hidden=not info.is_visible,
                is_number=info.is_number,
                organism_param=info.organism_param,
                is_tree=info.allowed_values_tree is not None,
                help=info.help,
                default=info.default_value,
                min=info.min,
                max=info.max,
                depends_on=list(info.vocab_depends_on or []),
                vocabulary=shown,
                vocabulary_total=len(options),
                vocabulary_note=_note(info, len(shown), len(options), facets),
                filter_facets=facets,
            )
        )
    return entries
