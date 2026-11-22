"""A follower re-read that fails is noted on a context read and raised on a write."""

from __future__ import annotations

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain.parameters import MultiPickValue
from veupathdb.errors import ValidationError, WDKError
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog import MovedParentError, read_under_parents
from veupathdb_mcp.catalog.param_dag import ParamFetcher

from .test_a_filter_statement_binds_by_its_facet import variant_characteristics
from .test_a_held_child_follows_a_changed_parent import _HELD, _PCHA

pytestmark = pytest.mark.skipif(
    needs_qa_recording("wdk/search_genes_by_ngs_snps.json"), reason=NEEDS_QA_RECORDING
)

_DOWN = "The site did not answer."


class _Site:
    def __init__(self, *, down_for_followers: bool) -> None:
        self.down_for_followers = down_for_followers
        self.contexts: list[dict[str, str]] = []

    async def __call__(self, context: dict[str, str]) -> list[WDKParameter]:
        self.contexts.append(dict(context))
        follower = (
            "organism_select_none" in context and "gene_variant_stats" not in context
        )
        if follower and self.down_for_followers:
            raise WDKError(_DOWN)
        return variant_characteristics()


def _reads() -> FilterReadsDouble:
    return FilterReadsDouble({"total_variants": "ontology_term_summary_total_variants"})


async def _read(
    fetch_at: ParamFetcher,
    stated: dict[str, JsonValue],
    stale: list[MovedParentError] | None,
) -> object:
    return await read_under_parents(
        fetch_at, stated, _reads(), about=None, bound=_HELD, stale=stale
    )


async def test_a_context_read_notes_a_follower_it_could_not_read() -> None:
    noted: list[MovedParentError] = []

    read = await _read(
        _Site(down_for_followers=True), {"organism_select_none": [_PCHA]}, noted
    )

    assert read == {"organism_select_none": MultiPickValue(values=[_PCHA])}
    [stale] = noted
    assert stale.child == "gene_variant_stats"
    assert _DOWN in str(stale.detail)


async def test_a_write_raises_a_follower_it_could_not_read() -> None:
    with pytest.raises(WDKError, match=_DOWN):
        await _read(
            _Site(down_for_followers=True), {"organism_select_none": [_PCHA]}, None
        )


def _follower_reads(site: _Site) -> int:
    return sum(
        1
        for context in site.contexts
        if "organism_select_none" in context and "gene_variant_stats" not in context
    )


async def test_a_refused_write_still_names_its_stale_follower() -> None:
    site = _Site(down_for_followers=False)

    with pytest.raises(ValidationError) as refused:
        await _read(site, {"organism_select_none": [_PCHA], "no_such": "x"}, None)

    assert _follower_reads(site) > 0
    assert "gene_variant_stats" in str(refused.value.detail)


async def test_a_refused_context_read_still_notes_every_stale_follower() -> None:
    site = _Site(down_for_followers=False)
    noted: list[MovedParentError] = []

    with pytest.raises(ValidationError):
        await _read(site, {"organism_select_none": [_PCHA], "no_such": "x"}, noted)

    assert _follower_reads(site) > 0
    assert [stale.child for stale in noted] == ["gene_variant_stats"]
