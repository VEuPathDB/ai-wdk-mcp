"""Measured notes for searches a site publishes no description for.

A note never replaces a description the site publishes."""

from collections.abc import Mapping

from veupathdb.wdk import WDKSearch

_SINGLE_COPY = (
    "Measured on OrthoMCL build 8.2: this search runs the same query as Number of "
    "Taxa (GroupsByGenomeCount). The same ranges return the same groups, and groups "
    "with several proteins in one genome are among them. It counts genomes of any "
    "clade and names no clade. One protein in every genome of a list or a clade is a "
    "GroupsByPhyleticPattern expression: L=NT AND L=N, with N the genome count "
    "lookup_phyletic_codes gives."
)

_NOTES: Mapping[tuple[str, str], str] = {
    ("orthomcl", "GroupsBySingleCopy"): _SINGLE_COPY
}


def described(site_id: str, search: WDKSearch) -> WDKSearch:
    note = _NOTES.get((site_id, search.url_segment), "")
    if search.description or not note:
        return search
    return search.model_copy(update={"description": note})
