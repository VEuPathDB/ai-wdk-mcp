from __future__ import annotations

import json
from typing import get_args

import pydantic
from pydantic import BaseModel, ConfigDict
from veupathdb.errors import WDKError
from veupathdb.jbrowse import GenomeReader, get_jbrowse_client
from veupathdb.wdk import (
    WDKAnswer,
    WDKRecordInstance,
    WDKSearchConfig,
    get_strategy_api,
    get_wdk_client,
)

from veupathdb_mcp.audit.frameshift import (
    FrameChange,
    ReferenceMiss,
    ReferenceRun,
    RepeatRun,
    VariantsUnread,
    flanked_span,
)
from veupathdb_mcp.audit.gene_models import (
    NO_RECORD,
    ModelRecord,
    ModelSpans,
    read_spans,
)
from veupathdb_mcp.audit.genes import report_of
from veupathdb_mcp.audit.length import LengthCheck
from veupathdb_mcp.audit.variant_calls import (
    VARIANT_RECORD_TYPE,
    VARIANT_SEARCH,
    VARIANT_TABLE,
    VariantCalls,
    VariantRecord,
    VariantTable,
    read_sites,
)
from veupathdb_mcp.audit.windows import DnaWindow, GenomeSource
from veupathdb_mcp.parse_failures import WrittenParseError

REFERENCE_PAD = 300
REFERENCE_MAX_BASES = 250_000
MAX_VARIANTS = 50
ANCHOR_BASES = 1
INVALID_VALUE = 422
_ORGANISM_PARAM = "organismSinglePick"
_VARIANT_TYPE = "variant_type"
_REFERENCE_ALLELE = "indel_ref_allele"
_FRAME_EFFECT = "indel_frame_effect"
_STATED_PARAMS = {
    "ReadFrequencyPercent": "20%",
    "MinPercentMinorAlleles": "0",
    "MinPercentIsolateCalls": "0",
}


class StrainReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    organism: str


class _VariantKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: str


def _strain_stretch(window: DnaWindow, run: RepeatRun) -> tuple[int, int]:
    low, high = sorted(
        (window.gene_strand_base(run.start), window.gene_strand_base(run.end))
    )
    return low, high + 1


async def _reference_runs(
    site_id: str, window: DnaWindow, shifts: list[RepeatRun], record: ModelRecord
) -> list[ReferenceRun | ReferenceMiss]:
    match read_spans(record.gene, record.rows):
        case ModelSpans() as spans:
            pass
        case _:
            return ["MODEL_UNREAD" for _ in shifts]
    first = min(start for start, _ in spans.cds) - REFERENCE_PAD
    last = max(end for _, end in spans.cds) + REFERENCE_PAD
    if last - first + 1 > REFERENCE_MAX_BASES:
        return ["WINDOW_TOO_LONG" for _ in shifts]
    source = GenomeSource(
        site=site_id, organism=record.model.organism_abbrev, seqid=spans.seqid
    )
    genome = GenomeReader(get_jbrowse_client(site_id))
    read = await genome.window(source.organism, spans.seqid, first, last)
    placed = DnaWindow(
        source=source,
        start=read.start,
        sequence=read.sequence,
        strand=spans.strand,
        at_contig_edge=False,
    )
    runs: list[ReferenceRun | ReferenceMiss] = []
    for shift in shifts:
        begin, end = _strain_stretch(window, shift)
        match flanked_span(window.on_gene_strand, begin, end, placed.on_gene_strand):
            case (int() as low, int() as high):
                ends = sorted(
                    (placed.genome_position(low), placed.genome_position(high - 1))
                )
                runs.append(
                    ReferenceRun(
                        gene=spans.gene,
                        source=source,
                        strand=spans.strand,
                        start=ends[0],
                        end=ends[1],
                        bases=high - low,
                    )
                )
            case miss:
                runs.append(miss)
    return runs


def _key(record: WDKRecordInstance) -> str:
    return next(part.value for part in record.id if part.name == "source_id")


def _complete(answer: WDKAnswer) -> bool:
    total = answer.meta.total_count
    return total is not None and total <= len(answer.records)


def _unread_status(exc: WDKError) -> VariantsUnread:
    if exc.status == NO_RECORD:
        return "NO_VARIANT_SEARCH"
    if exc.status == INVALID_VALUE:
        return "SEARCH_REFUSED"
    raise exc


async def _variant_params(
    site_id: str, organism: str
) -> dict[str, str] | VariantsUnread:
    context = {_ORGANISM_PARAM: json.dumps([organism])}
    try:
        details = await get_wdk_client(site_id).get_search_details_with_params(
            VARIANT_RECORD_TYPE, VARIANT_SEARCH, context
        )
    except WDKError as exc:
        return _unread_status(exc)
    served = {
        param.name: param.initial_display_value
        for param in details.search_data.parameters or []
        if param.initial_display_value is not None
    }
    return {**served, **context, **_STATED_PARAMS}


async def _variant_keys(
    site_id: str, params: dict[str, str], seqid: str, start: int, end: int
) -> list[list[_VariantKey]] | VariantsUnread:
    answer = await get_wdk_client(site_id).run_search_report(
        VARIANT_RECORD_TYPE,
        VARIANT_SEARCH,
        WDKSearchConfig(
            parameters={
                **params,
                "sequenceId": seqid,
                "start_point": str(start),
                "end_point": str(end),
            }
        ),
        report_of(["primary_key"], MAX_VARIANTS),
    )
    if not _complete(answer):
        return "TOO_MANY_VARIANTS"
    return [
        [_VariantKey(name=part.name, value=part.value) for part in record.id]
        for record in answer.records
    ]


def variant_record(record: WDKRecordInstance) -> VariantRecord:
    try:
        return VariantRecord(
            variant=_key(record),
            variant_type=record.attribute_text(_VARIANT_TYPE),
            reference_allele=record.attribute_text(_REFERENCE_ALLELE),
            frame_effect=record.attribute_text(_FRAME_EFFECT),
            rows=VariantTable.model_validate(record.tables).rows,
        )
    except pydantic.ValidationError as exc:
        msg = f"the variation record of {_key(record)} cannot be read"
        raise WrittenParseError(msg) from exc


def _homopolymer(run: RepeatRun | None, reference: ReferenceRun) -> int | None:
    if run is None or len(run.unit) != 1:
        return None
    return max(run.bases, reference.bases)


async def _calls(
    site_id: str,
    audited: str,
    organism: str,
    params: dict[str, str],
    shift: FrameChange,
    run: ReferenceRun,
) -> VariantCalls | VariantsUnread:
    start = run.start - ANCHOR_BASES
    end = run.end + ANCHOR_BASES
    try:
        keys = await _variant_keys(site_id, params, run.source.seqid, start, end)
    except WDKError as exc:
        return _unread_status(exc)
    match keys:
        case str() as unread:
            return unread
        case _:
            pass
    api = get_strategy_api(site_id)
    records = [
        variant_record(
            await api.get_single_record(
                VARIANT_RECORD_TYPE,
                [part.model_dump() for part in key],
                attributes=[_VARIANT_TYPE, _REFERENCE_ALLELE, _FRAME_EFFECT],
                tables=[VARIANT_TABLE],
            ),
        )
        for key in keys
    ]
    sites, samples = read_sites(audited, records)
    return VariantCalls(
        site=site_id,
        organism=organism,
        seqid=run.source.seqid,
        start=start,
        end=end,
        sites=sites,
        samples=samples,
        homopolymer_bases=_homopolymer(shift.run, run),
    )


async def _compared(
    site_id: str,
    audited: str,
    organism: str,
    params: dict[str, str] | VariantsUnread,
    shift: FrameChange,
    run: ReferenceRun | ReferenceMiss,
) -> FrameChange:
    match run, params:
        case ReferenceRun(), str() as unread:
            return shift.model_copy(
                update={"reference_run": run, "variants_unread": unread}
            )
        case ReferenceRun(), dict():
            match await _calls(site_id, audited, organism, params, shift, run):
                case VariantCalls() as calls:
                    update: dict[str, object] = {"variant_calls": calls}
                case unread:
                    update = {"variants_unread": unread}
            return shift.model_copy(update={"reference_run": run, **update})
        case miss, _:
            return shift.model_copy(
                update={"reference_unread": miss, "variants_unread": "NO_REFERENCE_RUN"}
            )


async def compared_to_reference(
    site_id: str,
    check: LengthCheck,
    window: DnaWindow,
    reference: StrainReference,
    record: ModelRecord,
) -> LengthCheck:
    repeats = [
        change.run
        for change in check.frame_changes
        if change.run_explains_shift and change.run is not None
    ]
    runs = await _reference_runs(site_id, window, repeats, record)
    params: dict[str, str] | VariantsUnread = "NO_REFERENCE_RUN"
    if any(run not in get_args(ReferenceMiss.__value__) for run in runs):
        params = await _variant_params(site_id, reference.organism)
    placed = iter(runs)
    compared = [
        await _compared(
            site_id,
            window.source.organism,
            reference.organism,
            params,
            change,
            next(placed),
        )
        if change.run_explains_shift
        else change
        for change in check.frame_changes
    ]
    return check.model_copy(update={"frame_changes": compared})
