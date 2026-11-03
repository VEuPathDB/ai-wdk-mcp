"""What a frameshift adds to a length check: the same stretch in the reference strain,
and what the site's variant calls say of the audited strain's reads there."""

from __future__ import annotations

import json

import pydantic
from pydantic import BaseModel, ConfigDict
from veupathdb.errors import DataParsingError, WDKError
from veupathdb.jbrowse import GenomeReader, get_jbrowse_client
from veupathdb.wdk import (
    WDKRecordInstance,
    WDKSearchConfig,
    get_strategy_api,
    get_wdk_client,
)

from veupathdb_mcp.audit.frameshift import (
    Frameshift,
    ReferenceRun,
    RepeatRun,
    flanks_of,
    reference_span,
)
from veupathdb_mcp.audit.gene_models import (
    NO_RECORD,
    ModelRecord,
    ModelSpans,
    read_spans,
)
from veupathdb_mcp.audit.genes import complete_answer, report_of
from veupathdb_mcp.audit.length import LengthCheck
from veupathdb_mcp.audit.variant_calls import (
    VARIANT_RECORD_TYPE,
    VARIANT_SEARCH,
    VARIANT_TABLE,
    VariantCalls,
    VariantRecord,
    VariantTable,
    judge_calls,
)
from veupathdb_mcp.audit.windows import DnaWindow, GenomeSource

REFERENCE_PAD = 300
REFERENCE_MAX_BASES = 250_000
MAX_VARIANTS = 50
ANCHOR_BASES = 1
INVALID_VALUE = 422
_ORGANISM_PARAM = "organismSinglePick"
_REFERENCE_ALLELE = "indel_ref_allele"
_STATED_PARAMS = {
    "variation_sample_meta": '{"filters":[]}',
    "ReadFrequencyPercent": "20%",
    "MinPercentMinorAlleles": "0",
    "MinPercentIsolateCalls": "0",
}


class StrainReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    organism: str


def _genome_run(
    spans: ModelSpans, abbrev: str, site_id: str, start: int, end: int
) -> ReferenceRun:
    return ReferenceRun(
        gene=spans.gene,
        source=GenomeSource(site=site_id, organism=abbrev, seqid=spans.seqid),
        strand=spans.strand,
        start=start,
        end=end,
        bases=end - start + 1,
    )


async def _reference_runs(
    site_id: str, window: DnaWindow, shifts: list[Frameshift], record: ModelRecord
) -> list[ReferenceRun | None]:
    match read_spans(record.gene, record.rows):
        case ModelSpans() as spans:
            pass
        case _:
            return [None for _ in shifts]
    first = min(start for start, _ in spans.cds) - REFERENCE_PAD
    last = max(end for _, end in spans.cds) + REFERENCE_PAD
    if last - first + 1 > REFERENCE_MAX_BASES:
        return [None for _ in shifts]
    abbrev = record.model.organism_abbrev
    genome = GenomeReader(get_jbrowse_client(site_id))
    read = await genome.window(abbrev, spans.seqid, first, last)
    placed = DnaWindow(
        source=GenomeSource(site=site_id, organism=abbrev, seqid=spans.seqid),
        start=read.start,
        sequence=read.sequence,
        strand=spans.strand,
        at_contig_edge=False,
    )
    runs: list[ReferenceRun | None] = []
    for shift in shifts:
        found = reference_span(placed.on_gene_strand, *flanks_of(window, shift))
        if found is None:
            runs.append(None)
            continue
        ends = sorted(
            (placed.genome_position(found[0]), placed.genome_position(found[1] - 1))
        )
        runs.append(_genome_run(spans, abbrev, site_id, ends[0], ends[1]))
    return runs


def _key(record: WDKRecordInstance) -> str:
    return next(part.value for part in record.id if part.name == "source_id")


async def _variant_ids(
    site_id: str, organism: str, seqid: str, start: int, end: int
) -> list[list[dict[str, str]]]:
    client = get_wdk_client(site_id)
    context = {_ORGANISM_PARAM: json.dumps([organism])}
    details = await client.get_search_details_with_params(
        VARIANT_RECORD_TYPE, VARIANT_SEARCH, context
    )
    served = {
        param.name: param.initial_display_value
        for param in details.search_data.parameters or []
        if param.initial_display_value is not None
    }
    answer = await client.run_search_report(
        VARIANT_RECORD_TYPE,
        VARIANT_SEARCH,
        WDKSearchConfig(
            parameters={
                **served,
                **context,
                **_STATED_PARAMS,
                "sequenceId": seqid,
                "start_point": str(start),
                "end_point": str(end),
            }
        ),
        report_of(["primary_key"], MAX_VARIANTS),
    )
    complete = complete_answer(answer, VARIANT_SEARCH)
    return [
        [{"name": part.name, "value": part.value} for part in record.id]
        for record in complete.records
    ]


def _variant_record(site_id: str, record: WDKRecordInstance) -> VariantRecord:
    try:
        table = VariantTable.model_validate(record.tables)
    except pydantic.ValidationError as exc:
        msg = (
            f"the variation record of {_key(record)} on {site_id} gives no readable "
            f"{VARIANT_TABLE}"
        )
        raise DataParsingError(msg) from exc
    return VariantRecord(
        variant=_key(record),
        reference_allele=record.attribute_text(_REFERENCE_ALLELE),
        rows=table.rows,
    )


def _homopolymer(run: RepeatRun | None, reference: ReferenceRun) -> int | None:
    if run is None or len(run.unit) != 1:
        return None
    return max(run.bases, reference.bases)


async def _calls(
    site_id: str, audited: str, organism: str, shift: Frameshift, run: ReferenceRun
) -> VariantCalls | None:
    start = run.start - ANCHOR_BASES
    end = run.end + ANCHOR_BASES
    try:
        keys = await _variant_ids(site_id, organism, run.source.seqid, start, end)
    except WDKError as exc:
        if exc.status in {NO_RECORD, INVALID_VALUE}:
            return None
        raise
    api = get_strategy_api(site_id)
    records = [
        _variant_record(
            site_id,
            await api.get_single_record(
                VARIANT_RECORD_TYPE,
                key,
                attributes=[_REFERENCE_ALLELE],
                tables=[VARIANT_TABLE],
            ),
        )
        for key in keys
    ]
    read = judge_calls(audited, records)
    return VariantCalls(
        site=site_id,
        organism=organism,
        seqid=run.source.seqid,
        start=start,
        end=end,
        variants=[record.variant for record in records],
        sample=read.sample,
        calls=read.calls,
        answer=read.answer,
        homopolymer_bases=_homopolymer(shift.run, run),
    )


async def compared_to_reference(
    site_id: str,
    check: LengthCheck,
    window: DnaWindow,
    reference: StrainReference,
    record: ModelRecord,
) -> LengthCheck:
    if not check.frameshifts:
        return check
    runs = await _reference_runs(site_id, window, check.frameshifts, record)
    compared: list[Frameshift] = []
    for shift, run in zip(check.frameshifts, runs, strict=True):
        calls = (
            None
            if run is None
            else await _calls(
                site_id, window.source.organism, reference.organism, shift, run
            )
        )
        compared.append(
            shift.model_copy(update={"reference_run": run, "variant_calls": calls})
        )
    return check.model_copy(update={"frameshifts": compared})
