"""The parameter sheet a model reads before it proposes values for a search."""

from __future__ import annotations

from pydantic import Field, JsonValue
from veupathdb.domain.parameters import FilterFacet, VocabOption
from veupathdb.model import CamelModel

from veupathdb_mcp.catalog.param_formatting import (
    ParameterInfo,
    cut_facets_note,
    shown_facets,
)
from veupathdb_mcp.catalog.shortlist import shortlist


class SheetEntry(CamelModel):
    """One parameter with everything needed to propose a value for it."""

    name: str
    display_name: str
    type: str
    required: bool
    is_number: bool = False
    organism_param: bool = False
    is_tree: bool = False
    help: str = ""
    default: JsonValue = None
    min: float | None = None
    max: float | None = None
    depends_on: list[str] = Field(default_factory=list)
    vocabulary: list[VocabOption] = Field(default_factory=list)
    vocabulary_total: int = 0
    vocabulary_note: str | None = None
    filter_facets: list[FilterFacet] = Field(default_factory=list)


def _note(
    info: ParameterInfo, shown: int, total: int, facets: list[FilterFacet]
) -> str | None:
    parts: list[str] = []
    # An empty vocabulary offers nothing, so its note is the reason it is empty.
    if not shown and info.allowed_values_note:
        parts.append(info.allowed_values_note)
    if total > shown:
        parts.append(
            f"{total} values; the {shown} most relevant to the request by name are "
            f"shown. If the value you need is absent, read {info.name} again with "
            f"query='<keyword>' before deciding it does not exist."
        )
    cut = cut_facets_note(info.name, info.facets(), facets)
    if cut:
        parts.append(cut)
    if info.allowed_values_tree is not None:
        parts.append("A parent term selects all of its children.")
    if info.stated_parents:
        parents = ", ".join(info.stated_parents)
        parts.append(
            f"This vocabulary depends on {parents} and is shown under the search defaults; "
            f"it is re-read under the values you propose."
        )
    return " ".join(parts) or None


def build_sheet(infos: list[ParameterInfo], *, query: str) -> list[SheetEntry]:
    """Every parameter a value can be proposed for. A vocabulary over
    ``DIRECT_MAX`` is shortlisted. A site-set parameter is never listed."""
    entries: list[SheetEntry] = []
    for info in infos:
        if info.site_set:
            continue
        options = info.vocabulary()
        shown = shortlist(options, query)
        facets = shown_facets(info.facets(), query)
        entries.append(
            SheetEntry(
                name=info.name,
                display_name=info.display_name,
                type=info.type,
                required=info.required,
                is_number=info.is_number,
                organism_param=info.organism_param,
                is_tree=info.allowed_values_tree is not None,
                help=info.help,
                default=info.default,
                min=info.min,
                max=info.max,
                depends_on=list(info.stated_parents),
                vocabulary=shown,
                vocabulary_total=len(options),
                vocabulary_note=_note(info, len(shown), len(options), facets),
                filter_facets=facets,
            )
        )
    return entries
