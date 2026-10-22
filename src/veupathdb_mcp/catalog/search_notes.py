"""Measured notes for searches a site publishes no description for.

A note never replaces a description the site publishes."""

from collections.abc import Mapping

from veupathdb.wdk import WDKSearch

_SINGLE_COPY = (
    "Measured on OrthoMCL build 8.2: this search returns the groups whose number of "
    "genomes with a protein, over all genomes, core genomes and peripheral genomes, "
    "falls in the three ranges. It does not limit the proteins of one genome, so a "
    "group it returns can hold several proteins in one genome; when it answers a "
    "single-copy question, state that limit. The three ranges apply together, and a "
    "group's all-genome count is its core count plus its peripheral count, so an "
    "all-genome range that starts above the sum of the core and peripheral maxima "
    "returns no group; widen those two ranges to reach it. Single copy over named "
    "genomes, a list "
    "or a clade L of N genomes, is the GroupsByPhyleticPattern expression L=NT AND "
    "L=N, one protein in every genome of L, with N the genome count "
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
