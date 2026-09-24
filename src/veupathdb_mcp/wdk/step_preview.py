"""Reads of one built WDK step that a tool or an endpoint renders directly:
the first records, and a temporary download URL."""

from veupathdb import JSONObject, strip_html_tags
from veupathdb.errors import VEuPathDBError
from veupathdb.wdk import (
    StrategyAPI,
    WDKAnswer,
    WDKRecordInstance,
    get_results_api,
    get_strategy_api,
)

from veupathdb_mcp.wdk.helpers import extract_pk
from veupathdb_mcp.wdk.step_results_models import SampleRecordsResult

_SAMPLE_PAGE_FACTOR = 4
"""Rows read for each gene a sample keeps, so repeated transcripts still fill it."""


async def step_download_url(
    site_id: str,
    step_id: int,
    *,
    output_format: str,
    attributes: list[str] | None = None,
) -> str:
    """Where the step's results download from, for as long as WDK keeps them.

    :raises WDKError: WDK refused the request.
    :raises OSError: The site was unreachable.
    """
    url: str = await get_results_api(site_id).get_download_url(
        step_id,
        output_format=output_format,
        attributes=attributes,
    )
    return url


async def step_sample_records(
    site_id: str,
    step_id: int,
    *,
    limit: int,
    attributes: list[str] | None = None,
) -> SampleRecordsResult:
    """The first records of a built step, with the HTML stripped from values.

    :raises WDKError: WDK refused the id-only read too.
    :raises OSError: The site was unreachable.
    """
    answer = await step_sample_answer(
        site_id, step_id, limit=limit, attributes=attributes
    )
    return _sample_of(answer, step_id)


async def step_sample_answer(
    site_id: str,
    step_id: int,
    *,
    limit: int,
    attributes: list[str] | None = None,
) -> WDKAnswer:
    """The first ``limit`` records of a built step, one row for each gene.

    The read sends no view filter: WDK ranks the whole answer to apply the
    representative transcript filter. A wider page holds the repeated rows.

    :raises WDKError: WDK refused the id-only read too.
    :raises OSError: The site was unreachable.
    """
    api = get_strategy_api(site_id)
    page_size = _SAMPLE_PAGE_FACTOR * limit
    first, accepted = await _first_page(api, step_id, page_size, attributes)
    records = _first_of_each_gene(first.records, limit)
    if len(records) < min(limit, first.meta.records_returned()):
        second = await api.get_step_answer(
            step_id,
            attributes=accepted,
            pagination={"offset": page_size, "numRecords": page_size},
        )
        records = _first_of_each_gene([*first.records, *second.records], limit)
    meta = first.meta.model_copy(update={"response_count": len(records)})
    return first.model_copy(update={"meta": meta, "records": records})


async def _first_page(
    api: StrategyAPI,
    step_id: int,
    page_size: int,
    attributes: list[str] | None,
) -> tuple[WDKAnswer, list[str] | None]:
    """A record class that rejects the attributes gets an id-only page."""
    pagination = {"offset": 0, "numRecords": page_size}
    if attributes:
        try:
            answer = await api.get_step_answer(
                step_id, attributes=attributes, pagination=pagination
            )
        except VEuPathDBError, OSError:
            pass  # The record class lacks these attributes.
        else:
            return answer, attributes
    return await api.get_step_answer(step_id, pagination=pagination), None


def _first_of_each_gene(
    records: list[WDKRecordInstance], limit: int
) -> list[WDKRecordInstance]:
    """A transcript row names its gene first in its primary key."""
    kept: dict[str, WDKRecordInstance] = {}
    for record in records:
        kept.setdefault(extract_pk(record) or record.display_name, record)
        if len(kept) == limit:
            break
    return list(kept.values())


def _sample_of(answer: WDKAnswer, step_id: int) -> SampleRecordsResult:
    records: list[JSONObject] = []
    for rec in answer.records:
        row: JSONObject = {"id": rec.display_name}
        for attr_name, attr_val in rec.attributes.items():
            row[attr_name] = (
                strip_html_tags(attr_val) if isinstance(attr_val, str) else attr_val
            )
        records.append(row)
    # The same count the size tool reports. The raw total counts the id query,
    # which is transcripts where the record class counts genes.
    return SampleRecordsResult(
        step_id=step_id,
        total_count=answer.meta.records_returned(),
        records=records,
        attributes=list(answer.meta.attributes or []),
    )
