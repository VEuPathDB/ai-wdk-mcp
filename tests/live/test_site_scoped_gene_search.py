"""A site's gene search answers with that site's organisms, against the real service."""

from __future__ import annotations

import pytest

from veupathdb_mcp.gene_lookup.organisms import list_organisms
from veupathdb_mcp.gene_lookup.site_search import (
    fetch_site_search_genes,
    stream_site_search_gene_ids,
)

pytestmark = pytest.mark.live_wdk

SITE = "plasmodb"


async def test_the_site_declares_its_own_organisms() -> None:
    declared = await list_organisms(SITE)

    assert declared
    assert all(
        "Plasmodium" in name or "Haemoproteus" in name or "Hepatocystis" in name
        for name in declared
    )


async def test_a_kinase_search_answers_with_the_sites_own_genes() -> None:
    declared = set(await list_organisms(SITE))

    results, offered, total = await fetch_site_search_genes(SITE, "kinase", limit=10)

    assert results
    assert {result.organism for result in results} <= declared
    assert set(offered) <= declared
    assert 0 < total < 100_000


async def test_the_stream_is_restricted_the_same_way() -> None:
    gene_ids = await stream_site_search_gene_ids(SITE, "kinase", max_records=200)

    assert 0 < len(gene_ids) <= 200
