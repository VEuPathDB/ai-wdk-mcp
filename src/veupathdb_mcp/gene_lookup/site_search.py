"""Site-search gene fetching and document parsing."""

from veupathdb.text import strip_html_tags
from veupathdb.wdk.site_router import get_site_router
from veupathdb.wdk.site_search_client import (
    DocumentTypeFilter,
    SiteSearchDocument,
)

from .organism import normalize_organism
from .organisms import list_organisms
from .result import GeneResult
from .wdk import normalize_gene_ids

GENE_DOCUMENT_TYPE = "gene"

SITE_SEARCH_PAGE_LIMIT = 50
"""The largest page site-search serves; ``MAX_RECORDS_IN_PAGED_RESPONSE`` upstream."""

SITE_SEARCH_STREAM_LIMIT = 5000
"""How many streamed identifiers one lookup reads.

The stream carries every match, so the bound is ours. Five thousand identifiers
of a plasmodb gene search measure about 139 KB and under three seconds.
"""


def _extract_gene_id(doc: SiteSearchDocument) -> str:
    """Extract the gene ID from a site-search document."""
    gene_id = strip_html_tags(doc.wdk_primary_key_string).strip()
    if not gene_id and doc.primary_key:
        gene_id = doc.primary_key[0].strip()
    return gene_id


def _extract_matched_fields(doc: SiteSearchDocument) -> list[str]:
    """Extract matched field names from a site-search document."""
    matched_fields: list[str] = []
    for field_key, field_values in doc.found_in_fields.items():
        if field_values:
            clean_key = field_key.replace("MULTITEXT__", "").replace("TEXT__", "")
            matched_fields.append(clean_key)
    return matched_fields


def parse_site_search_docs(docs: list[SiteSearchDocument]) -> list[GeneResult]:
    """Convert typed site-search documents into standardised gene results."""
    results: list[GeneResult] = []
    for doc in docs:
        gene_id = _extract_gene_id(doc)
        if not gene_id:
            continue

        summary = doc.summary_field_data

        doc_organism = normalize_organism(
            str(summary.get("TEXT__gene_organism_full", ""))
        )
        doc_product = strip_html_tags(str(summary.get("TEXT__gene_product", "")))
        doc_gene_name = strip_html_tags(str(summary.get("TEXT__gene_name", "")))
        doc_gene_type = strip_html_tags(str(summary.get("TEXT__gene_type", "")))

        hyperlink_name = strip_html_tags(doc.hyperlink_name).strip()
        display_name = hyperlink_name or doc_gene_name or doc_product

        if not doc_organism and doc.organism:
            doc_organism = normalize_organism(doc.organism[0])

        results.append(
            GeneResult(
                gene_id=gene_id,
                display_name=display_name,
                organism=doc_organism,
                product=doc_product,
                gene_name=doc_gene_name,
                gene_type=doc_gene_type,
                matched_fields=_extract_matched_fields(doc),
            )
        )
    return results


async def fetch_site_search_genes(
    site_id: str,
    search_text: str,
    *,
    organisms: list[str] | None = None,
    limit: int = SITE_SEARCH_PAGE_LIMIT,
) -> tuple[list[GeneResult], list[str], int]:
    """Run a single site-search query and return parsed results.

    One SOLR index serves every site and gene documents carry no project, so a
    query that names no organism is restricted to the site's own list.

    :returns: ``(gene_results, available_organisms, total_count)``
    """
    site_organisms = await list_organisms(site_id)
    response = (
        await get_site_router()
        .get_site_search_client(site_id)
        .search(
            search_text,
            document_type_filter=DocumentTypeFilter(document_type=GENE_DOCUMENT_TYPE),
            organisms=organisms or site_organisms or None,
            restrict_metadata_to_organisms=site_organisms or None,
            limit=limit,
            offset=0,
        )
    )

    results = parse_site_search_docs(response.search_results.documents)
    orgs = sorted(response.organism_counts.keys())
    total = response.search_results.total_count

    return results, orgs, total


async def stream_site_search_gene_ids(
    site_id: str,
    search_text: str,
    *,
    organisms: list[str] | None = None,
    max_records: int = SITE_SEARCH_STREAM_LIMIT,
) -> list[str]:
    """Gene identifiers from the streaming form, in the service's score order.

    The paged form stops at fifty records; this one reaches the whole match set.
    """
    site_organisms = await list_organisms(site_id)
    records = await (
        get_site_router()
        .get_site_search_client(site_id)
        .stream_records(
            search_text,
            document_type=GENE_DOCUMENT_TYPE,
            organisms=organisms or site_organisms or None,
            max_records=max_records,
        )
    )
    return normalize_gene_ids(
        [record.primary_key[0] for record in records if record.primary_key]
    )
