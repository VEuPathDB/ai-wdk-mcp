"""WDK-based gene search and ID resolution."""

import json
from dataclasses import dataclass

from veupathdb.errors import VEuPathDBError
from veupathdb.json_types import JSONObject
from veupathdb.logging import get_logger
from veupathdb.settings import get_veupathdb_settings
from veupathdb.text import strip_html_tags
from veupathdb.wdk.client import VEuPathDBClient
from veupathdb.wdk.factory import get_wdk_client
from veupathdb.wdk.site_router import get_site_router
from veupathdb.wdk.strategy_api.api import StrategyAPI
from veupathdb.wdk.wdk_models import (
    WDKAnswer,
    WDKDatasetConfigIdList,
    WDKDatasetIdListContent,
    WDKRecordInstance,
    WDKSearchConfig,
)

from .organism import normalize_organism
from .result import DEFAULT_GENE_ATTRIBUTES, GeneResult

logger = get_logger(__name__)

WDK_WILDCARD_LIMIT = 50

MAX_GENE_IDS = 200
"""The largest identifier list one resolve call accepts."""


def normalize_gene_ids(gene_ids: list[str]) -> list[str]:
    """Trim a gene identifier list, drop the blanks, and keep the first of each."""
    return list(dict.fromkeys(value.strip() for value in gene_ids if value.strip()))


WDK_TEXT_FIELDS_ID: list[str] = ["primary_key", "Alias"]
WDK_TEXT_FIELDS_BROAD: list[str] = [
    "product",
    "name",
    "primary_key",
    "Alias",
    "GOTerms",
    "Notes",
    "Products",
]


@dataclass
class WdkTextResult:
    """Results from a WDK ``GenesByText`` query."""

    records: list[GeneResult]
    total_count: int


@dataclass
class GeneResolveResult:
    """Typed result from gene ID resolution."""

    records: list[GeneResult]
    total_count: int
    error: str | None = None


def _parse_wdk_record(rec: WDKRecordInstance) -> GeneResult | None:
    """Parse a WDK record instance into a typed GeneResult."""
    rec_attrs = rec.attributes
    gene_id = ""
    for elem in rec.id:
        if elem.name in ("gene_source_id", "source_id", "gene") and elem.value.strip():
            gene_id = elem.value.strip()
            break

    if not gene_id:
        gene_id = str(rec_attrs.get("primary_key", "")).strip()

    gene_name_raw = rec_attrs.get("gene_name", "")
    gene_name = strip_html_tags(str(gene_name_raw)) if gene_name_raw else ""
    product_raw = rec_attrs.get("gene_product", "")
    product = strip_html_tags(str(product_raw)) if product_raw else ""
    organism_raw = rec_attrs.get("organism", "")
    org = normalize_organism(str(organism_raw)) if organism_raw else ""
    gene_type = str(rec_attrs.get("gene_type", ""))
    location = str(rec_attrs.get("gene_location_text", ""))
    gene_source_id = str(rec_attrs.get("gene_source_id", ""))
    previous_ids = str(rec_attrs.get("gene_previous_ids", ""))

    return GeneResult(
        gene_id=gene_source_id or gene_id,
        display_name=gene_name or product or gene_id,
        organism=org,
        product=product,
        gene_name=gene_name,
        gene_type=gene_type,
        location=location,
        previous_ids=previous_ids or "",
    )


async def fetch_wdk_text_genes(
    site_id: str,
    expressions: list[str],
    *,
    organism: str | None = None,
    text_fields: list[str] | None = None,
    record_type: str = "transcript",
    limit: int = WDK_WILDCARD_LIMIT,
) -> WdkTextResult:
    """Search genes via WDK ``GenesByText``."""
    if not expressions or not organism:
        return WdkTextResult(records=[], total_count=0)

    fields = text_fields or WDK_TEXT_FIELDS_ID
    client = get_wdk_client(site_id)

    all_results: list[GeneResult] = []
    wdk_total: int = 0
    for pattern in expressions:
        report_config: JSONObject = {
            "attributes": list(DEFAULT_GENE_ATTRIBUTES),
            "tables": [],
            "pagination": {"offset": 0, "numRecords": limit},
        }
        try:
            answer = await client.run_search_report(
                record_type=record_type,
                search_name="GenesByText",
                search_config=WDKSearchConfig(
                    parameters={
                        "text_expression": pattern,
                        "text_fields": json.dumps(fields),
                        "text_search_organism": json.dumps([organism]),
                        "document_type": "gene",
                    },
                ),
                report_config=report_config,
            )
        except VEuPathDBError:
            continue
        wdk_total = max(wdk_total, answer.meta.records_returned())
        for rec in answer.records:
            parsed = _parse_wdk_record(rec)
            if parsed:
                all_results.append(parsed)
        if len(all_results) >= limit:
            break

    records = all_results[:limit]
    return WdkTextResult(
        records=records,
        total_count=max(wdk_total, len(records)),
    )


def _build_gene_result_from_answer(answer: WDKAnswer | None) -> GeneResolveResult:
    """Build the final gene result from a WDK answer."""
    if answer is None:
        return GeneResolveResult(records=[], total_count=0)
    return _parse_records_to_result(answer)


def _parse_records_to_result(answer: WDKAnswer) -> GeneResolveResult:
    """Parse WDK answer records into the final gene result."""
    records: list[GeneResult] = []
    for rec in answer.records:
        parsed = _parse_wdk_record(rec)
        if parsed:
            records.append(parsed)
    return GeneResolveResult(
        records=records, total_count=answer.meta.records_returned()
    )


def _empty_gene_result(error: str | None = None) -> GeneResolveResult:
    """Return an empty gene result, optionally with an error message."""
    return GeneResolveResult(records=[], total_count=0, error=error)


async def _fetch_gene_answer(
    client: VEuPathDBClient,
    gene_ids: list[str],
    record_type: str,
    search_name: str,
    param_name: str,
    attrs: list[str],
) -> WDKAnswer | None:
    """Create a WDK dataset for gene_ids and run a standard reporter query.

    Returns the typed WDKAnswer, or None if dataset creation or search fails.
    """
    api = StrategyAPI(client)
    config = WDKDatasetConfigIdList(
        source_type="idList",
        source_content=WDKDatasetIdListContent(ids=gene_ids),
    )
    try:
        dataset_id = await api.create_dataset(config)
    except VEuPathDBError:
        return None

    report_config: JSONObject = {"attributes": list(attrs), "tables": []}
    try:
        return await client.run_search_report(
            record_type=record_type,
            search_name=search_name,
            search_config=WDKSearchConfig(parameters={param_name: str(dataset_id)}),
            report_config=report_config,
        )
    except VEuPathDBError:
        return None


async def resolve_gene_ids(
    site_id: str,
    gene_ids: list[str],
    *,
    record_type: str = "transcript",
    search_name: str = "GeneByLocusTag",
    param_name: str = "ds_gene_ids",
    attributes: list[str] | None = None,
) -> GeneResolveResult:
    """Resolve gene IDs to full records through the WDK standard reporter.

    The client is short-lived and private, because WDK ties a dataset to the
    session that created it and a shared cookie jar breaks that affinity.
    """
    if not gene_ids:
        return _empty_gene_result()

    router = get_site_router()
    site = router.get_site(site_id)
    settings = get_veupathdb_settings()
    routing = router._config.routing
    timeout = float(
        routing.portal_timeout if site.is_portal else routing.component_timeout
    )

    client = VEuPathDBClient(
        base_url=site.service_url,
        timeout=timeout,
        auth_token=settings.veupathdb_auth_token,
    )
    attrs = attributes or DEFAULT_GENE_ATTRIBUTES

    try:
        answer = await _fetch_gene_answer(
            client, gene_ids, record_type, search_name, param_name, attrs
        )
    except VEuPathDBError as exc:
        logger.warning(
            "Gene ID resolution via standard reporter failed",
            site_id=site_id,
            gene_ids_count=len(gene_ids),
            error=str(exc),
        )
        return _empty_gene_result(f"WDK lookup failed: {exc}")
    finally:
        await client.close()

    return _build_gene_result_from_answer(answer)
