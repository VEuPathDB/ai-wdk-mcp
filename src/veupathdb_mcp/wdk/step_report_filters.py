"""The view filters a step report sends, chosen by the record type of the step.

A transcript step reports one row per transcript and counts genes. The
representative transcript filter makes the rows one per gene.
"""

from veupathdb.wdk import StrategyAPI, WDKFilterValue


def representative_transcript_only() -> WDKFilterValue:
    """The WDK view filter that keeps one transcript row for each gene."""
    return WDKFilterValue(name="representativeTranscriptOnly", value={})


def view_filters_for(record_type: str | None) -> list[WDKFilterValue] | None:
    """The view filters a report on a step of this record type sends."""
    if record_type == "transcript":
        return [representative_transcript_only()]
    return None


async def step_view_filters(
    api: StrategyAPI, step_id: int
) -> list[WDKFilterValue] | None:
    """The view filters for a step, from the record type WDK reports for it."""
    step = await api.find_step(step_id)
    return view_filters_for(step.record_class_name)
