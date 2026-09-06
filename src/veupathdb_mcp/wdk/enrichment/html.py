"""HTML-embedded gene list extraction from WDK enrichment results.

Pure module (no I/O). Parses gene counts and gene IDs from the HTML
``<a>`` tags that WDK enrichment plugins emit in their ``resultGenes``
field.
"""

import re

_LINK_COUNT_RE = re.compile(r">(\d+)<")
_IDLIST_RE = re.compile(r"idList=([^&'\"]+)")


def parse_result_genes_html(html: str) -> tuple[int, list[str]]:
    """Extract gene count and gene IDs from a WDK ``resultGenes`` HTML link.

    WDK enrichment plugins render gene counts as hyperlinks::

        <a href='...?param.ds_gene_ids.idList=GENE1,GENE2,...&autoRun=1'>32</a>

    Returns ``(count, gene_ids)``.
    """
    count = 0
    count_m = _LINK_COUNT_RE.search(html)
    if count_m:
        count = int(count_m.group(1))

    genes: list[str] = []
    id_m = _IDLIST_RE.search(html)
    if id_m:
        genes = [g.strip() for g in id_m.group(1).split(",") if g.strip()]
    return count, genes
