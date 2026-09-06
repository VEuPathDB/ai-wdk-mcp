"""Reads of one built WDK step that a tool or an endpoint renders directly:
the first records, and a temporary download URL."""

from veupathdb.errors import VEuPathDBError
from veupathdb.json_types import JSONObject
from veupathdb.text import strip_html_tags
from veupathdb.wdk.factory import get_results_api, get_strategy_api
from veupathdb.wdk.strategy_api import StrategyAPI
from veupathdb.wdk.wdk_models import WDKAnswer

from veupathdb_mcp.wdk.step_results_models import SampleRecordsResult


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
    answer = await _preview(
        get_strategy_api(site_id),
        step_id,
        limit=limit,
        attributes=attributes,
    )
    return _sample_of(answer, step_id)


async def _preview(
    api: StrategyAPI,
    step_id: int,
    *,
    limit: int,
    attributes: list[str] | None,
) -> WDKAnswer:
    """A record class that rejects the attributes gets an id-only preview."""
    pagination = {"offset": 0, "numRecords": limit}
    if attributes:
        try:
            return await api.get_step_answer(
                step_id,
                attributes=attributes,
                pagination=pagination,
            )
        except VEuPathDBError, OSError:
            pass  # The record class lacks these attributes.
    return await api.get_step_answer(step_id, pagination=pagination)


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
