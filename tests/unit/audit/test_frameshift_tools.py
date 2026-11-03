import json
from typing import Literal

import pytest
from fastmcp.exceptions import ToolError
from tests._support.audit_site import Contig
from tests._support.nf54_frameshift import (
    MODEL_PROTEIN,
    REFERENCE_PROTEIN,
    model_coding,
    reference_coding,
    run_offset,
)
from tests._support.proteins import row
from tests._support.strain_site import REFERENCE, STRAIN, StrainSite, strain_site
from tests._support.variant_wire import (
    INDEL_ID,
    SERVED_INDEL,
    SERVED_SNV,
    SNV_ID,
    WIRE,
)
from veupathdb.errors import WDKError
from veupathdb.wdk import (
    WDKAnswer,
    WDKRecordInstance,
    WDKSearchConfig,
    WDKSearchResponse,
)

from veupathdb_mcp.audit import frameshift_inputs
from veupathdb_mcp.audit.codes import reverse_complement
from veupathdb_mcp.audit.frameshift import FrameChange, SplicePair
from veupathdb_mcp.audit.frameshift_inputs import StrainReference
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GroupMember, OrthologGroup
from veupathdb_mcp.audit.length import LengthCheck
from veupathdb_mcp.audit.pseudogene import CdsPart
from veupathdb_mcp.audit.served import LengthDna
from veupathdb_mcp.audit.windows import GenomeSource
from veupathdb_mcp.parse_failures import WrittenParseError
from veupathdb_mcp.tools import audit_strain_tools, audit_tools
from veupathdb_mcp.tools.audit_strain_tools import audit_strain_model

PAD = 8000
CONSTRUCTED_GENOME = "pfalConstructed"
CONSTRUCTED_SAMPLE = "CONSTRUCTED_SAMPLE"
ME = "constructed_gene"
ME_ORGANISM = "Plasmodium falciparum Constructed"
REFERENCE_ORGANISM = "Plasmodium falciparum 3D7"


def constructed_site(
    monkeypatch: pytest.MonkeyPatch, *, strand: Literal["+", "-"] = "+"
) -> StrainSite:
    site = strain_site(monkeypatch, (MODEL_PROTEIN, REFERENCE_PROTEIN))
    strain, reference, *others = site.rows
    strain_dna = model_coding()
    reference_dna = reference_coding() + "TAA"
    strain_cds = CdsPart(start=PAD + 1, end=PAD + 3 * len(MODEL_PROTEIN) + 3)
    reference_cds = CdsPart(start=PAD + 1, end=PAD + len(reference_dna))
    site.rows = [
        strain.model_copy(
            update={
                "start": strain_cds.start,
                "end": strain_cds.end,
                "organism": "Plasmodium falciparum Constructed",
            }
        ),
        reference.model_copy(
            update={
                "start": reference_cds.start,
                "end": reference_cds.end,
                "strand": strand,
            }
        ),
        *others,
    ]
    site.orthologs[REFERENCE] = site.rows
    site.models[STRAIN] = GeneModel(
        organism_abbrev=CONSTRUCTED_GENOME, cds=[strain_cds]
    )
    site.models[REFERENCE] = GeneModel(organism_abbrev="pfal3D7", cds=[reference_cds])
    flank = "C" * PAD
    site.contigs[CONSTRUCTED_GENOME, strain.sequence_id] = Contig.whole(
        flank + strain_dna + flank + flank
    )
    placed = flank + reference_dna + flank
    if strand == "-":
        size = len(placed)
        cds = CdsPart(
            start=size - reference_cds.end + 1, end=size - reference_cds.start + 1
        )
        site.models[REFERENCE] = GeneModel(organism_abbrev="pfal3D7", cds=[cds])
        placed = reverse_complement(placed)
    site.contigs["pfal3D7", reference.sequence_id] = Contig.whole(placed)
    return site


class ServedVariants:
    def __init__(
        self, answer: WDKAnswer, records: dict[str, WDKRecordInstance]
    ) -> None:
        self.answer = answer
        self.records = records
        self.contexts: list[dict[str, str]] = []
        self.searches: list[WDKSearchConfig] = []
        self.read: list[str] = []
        self.asked: list[tuple[list[str], list[str]]] = []
        self.refusal: WDKError | None = None

    async def get_search_details_with_params(
        self, record_type: str, search_name: str, context: dict[str, str]
    ) -> WDKSearchResponse:
        self.contexts.append(context)
        if self.refusal is not None:
            raise self.refusal
        return WIRE.details

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: dict[str, object],
    ) -> WDKAnswer:
        self.searches.append(search_config)
        return self.answer

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        name = next(p["value"] for p in primary_key if p["name"] == "source_id")
        self.read.append(name)
        self.asked.append((attributes, tables))
        return self.records[name]


def install(monkeypatch: pytest.MonkeyPatch, wire: ServedVariants) -> ServedVariants:
    monkeypatch.setattr(frameshift_inputs, "get_wdk_client", lambda site_id: wire)
    monkeypatch.setattr(frameshift_inputs, "get_strategy_api", lambda site_id: wire)
    return wire


def served_snv(monkeypatch: pytest.MonkeyPatch) -> ServedVariants:
    return install(monkeypatch, ServedVariants(WIRE.search, {SNV_ID: SERVED_SNV}))


def answer_of(names: list[str], total: int) -> WDKAnswer:
    body = WIRE.search.model_dump(by_alias=True)
    template = body["records"][0]
    body["records"] = [
        {**template, "id": [{"name": "source_id", "value": name}]} for name in names
    ]
    body["meta"]["totalCount"] = total
    return WDKAnswer.model_validate(body)


def with_constructed_sample(
    record: WDKRecordInstance, genotype: str, effect: str | None
) -> WDKRecordInstance:
    row_of = {
        "strain": CONSTRUCTED_SAMPLE,
        "genotype": genotype,
        "allele": "G",
        "depth": "1",
        "read_frequency": "100.00",
    }
    return record.model_copy(
        update={
            "tables": {"VariantStrains": [row_of]},
            "attributes": {**record.attributes, "indel_frame_effect": effect},
        }
    )


@pytest.mark.parametrize("strand", ["+", "-"])
async def test_a_strain_frameshift_reads_the_run_in_the_reference_strain(
    monkeypatch: pytest.MonkeyPatch, strand: Literal["+", "-"]
) -> None:
    site = constructed_site(monkeypatch, strand=strand)
    wire = served_snv(monkeypatch)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert result.dna.verdict == "FRAMESHIFT"
    assert result.side == "UNCLEAR"
    shift = result.dna.frame_changes[0]
    assert shift.run is not None
    assert (shift.run.unit, shift.run.bases) == ("A", 29)
    run = shift.reference_run
    assert run is not None
    assert (run.gene, run.bases, run.strand) == (REFERENCE, 28, strand)
    assert run.source.site == "plasmodb"
    assert run.source.organism == "pfal3D7"
    contig = site.contigs["pfal3D7", run.source.seqid].sequence
    held = contig[run.start - 1 : run.end]
    assert held == ("A" if strand == "+" else "T") * 28
    if strand == "+":
        first = PAD + 1 + run_offset(reference_coding())
        assert (run.start, run.end) == (first, first + 27)
    assert site.models_read.count(REFERENCE) == 1
    assert wire.contexts == [{"organismSinglePick": json.dumps([REFERENCE_ORGANISM])}]


async def test_the_search_replaces_every_placeholder_the_site_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_site(monkeypatch)
    wire = served_snv(monkeypatch)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    shift = result.dna.frame_changes[0]
    run = shift.reference_run
    assert run is not None
    [search] = wire.searches
    assert search.parameters == {
        "organismSinglePick": json.dumps([REFERENCE_ORGANISM]),
        "eda_sample_table_suffix": "s3be28bbe14_sample",
        "chromosomeOptionalForVariations": "Choose chromosome",
        "sequenceId": run.source.seqid,
        "start_point": str(run.start - 1),
        "end_point": str(run.end + 1),
        "variation_sample_meta": '{"filters":[]}',
        "WebServicesPath": "dflt",
        "ReadFrequencyPercent": "20%",
        "MinPercentMinorAlleles": "0",
        "MinPercentIsolateCalls": "0",
    }


async def test_the_recorded_search_names_what_it_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_site(monkeypatch)
    wire = served_snv(monkeypatch)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    shift = result.dna.frame_changes[0]
    calls = shift.variant_calls
    run = shift.reference_run
    assert calls is not None
    assert run is not None
    assert (calls.site, calls.record_type, calls.search, calls.table) == (
        "plasmodb",
        "variation",
        "VariantsByLocation",
        "VariantStrains",
    )
    assert calls.samples == []
    assert [(site.variant, site.variant_type) for site in calls.sites] == [
        (SNV_ID, "SNV")
    ]
    assert calls.homopolymer_bases == 29
    assert (calls.start, calls.end) == (run.start - 1, run.end + 1)
    assert wire.read == [SNV_ID]
    assert shift.counts_match_shift is True


async def test_a_call_in_the_constructed_sample_is_stated_with_its_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_site(monkeypatch)
    wire = install(
        monkeypatch,
        ServedVariants(
            answer_of([INDEL_ID], 1),
            {INDEL_ID: with_constructed_sample(SERVED_INDEL, "1", "inframe_deletion")},
        ),
    )

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    calls = result.dna.frame_changes[0].variant_calls
    assert calls is not None
    assert calls.samples == [CONSTRUCTED_SAMPLE]
    [site] = calls.sites
    assert (site.variant_type, site.indel_ref_allele, site.indel_frame_effect) == (
        "MIXED",
        "GAGGAAA",
        "inframe_deletion",
    )
    assert [(c.sample, c.genotype, c.allele) for c in site.calls] == [
        (CONSTRUCTED_SAMPLE, "1", "G")
    ]
    assert wire.asked == [
        (
            ["variant_type", "indel_ref_allele", "indel_frame_effect"],
            ["VariantStrains"],
        )
    ]


async def test_no_variant_over_a_long_run_says_little(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_site(monkeypatch)
    install(monkeypatch, ServedVariants(answer_of([], 0), {}))

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    calls = result.dna.frame_changes[0].variant_calls
    assert calls is not None
    assert calls.sites == []
    assert calls.calls_say_little


async def test_more_variants_than_the_bound_keep_the_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_site(monkeypatch)
    wire = install(monkeypatch, ServedVariants(answer_of([SNV_ID], 51), {}))

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert result.dna.verdict == "FRAMESHIFT"
    shift = result.dna.frame_changes[0]
    assert (shift.variant_calls, shift.variants_unread) == (None, "TOO_MANY_VARIANTS")
    assert wire.read == []


@pytest.mark.parametrize(
    ("status", "reason"), [(404, "NO_VARIANT_SEARCH"), (422, "SEARCH_REFUSED")]
)
async def test_a_refused_search_is_unread_and_names_why(
    monkeypatch: pytest.MonkeyPatch, status: int, reason: str
) -> None:
    constructed_site(monkeypatch)
    wire = served_snv(monkeypatch)
    wire.refusal = WDKError("refused", status=status)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    shift = result.dna.frame_changes[0]
    assert shift.reference_run is not None
    assert (shift.variant_calls, shift.variants_unread) == (None, reason)


async def test_the_recorded_refusal_is_the_status_read_as_refused() -> None:
    assert WIRE.refused_status == 422


async def test_any_other_status_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_site(monkeypatch)
    wire = served_snv(monkeypatch)
    wire.refusal = WDKError("broken", status=500)

    with pytest.raises(Exception, match=r"broken|500"):
        await audit_strain_model("plasmodb", STRAIN, REFERENCE)


async def test_a_reference_without_the_flanks_says_why_and_reads_no_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = constructed_site(monkeypatch)
    wire = served_snv(monkeypatch)
    placed = site.rows[1]
    length = len(site.contigs["pfal3D7", placed.sequence_id].sequence)
    site.contigs["pfal3D7", placed.sequence_id] = Contig.whole("C" * length)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    shift = result.dna.frame_changes[0]
    assert (shift.reference_run, shift.reference_unread) == (None, "FLANK_MISSING")
    assert shift.variants_unread == "NO_REFERENCE_RUN"
    assert wire.searches == []


def length_site(
    monkeypatch: pytest.MonkeyPatch, members: list[GroupMember]
) -> StrainSite:
    site = constructed_site(monkeypatch)
    placed = site.rows[0]
    me = placed.model_copy(update={"gene": ME, "organism": ME_ORGANISM})
    site.rows = [me, *site.rows[1:]]
    site.proteins[ME] = MODEL_PROTEIN
    site.models[ME] = GeneModel(
        organism_abbrev=CONSTRUCTED_GENOME, cds=site.models[STRAIN].cds
    )
    site.orthologs[ME] = site.rows
    long = len(REFERENCE_PROTEIN)
    site.proteins.update({f"K{i}": REFERENCE_PROTEIN for i in range(8)})
    relatives = [
        GroupMember.of_row(row(f"K{i}", f"Plasmodium species{i} X", long))
        for i in range(8)
    ]

    async def orthologs(site_id: str, gene: str) -> OrthologGroup:
        return OrthologGroup(
            gene=gene, members=[GroupMember.of_row(me), *members, *relatives]
        )

    monkeypatch.setattr("veupathdb_mcp.audit.served.orthologs_of", orthologs)
    return site


def member_of(gene: str, organism: str, *, marked: bool) -> GroupMember:
    length = len(REFERENCE_PROTEIN)
    return GroupMember.of_row(row(gene, organism, length)).model_copy(
        update={"reference_strain": marked}
    )


async def test_a_length_frameshift_compares_with_the_marked_reference_strain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    length_site(
        monkeypatch,
        [
            member_of(REFERENCE, REFERENCE_ORGANISM, marked=True),
            member_of("constructed_other", "Plasmodium falciparum Other", marked=False),
        ],
    )
    wire = served_snv(monkeypatch)

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "FRAMESHIFT"
    shift = result.frame_changes[0]
    assert shift.source.organism == CONSTRUCTED_GENOME
    assert shift.reference_run is not None
    assert (shift.reference_run.gene, shift.reference_run.bases) == (REFERENCE, 28)
    assert wire.contexts == [{"organismSinglePick": json.dumps([REFERENCE_ORGANISM])}]


@pytest.mark.parametrize(
    "members",
    [
        [
            member_of(REFERENCE, REFERENCE_ORGANISM, marked=True),
            member_of("constructed_other", "Plasmodium falciparum Other", marked=True),
        ],
        [member_of(REFERENCE, "Plasmodium vivax Constructed", marked=True)],
        [member_of(REFERENCE, REFERENCE_ORGANISM, marked=False)],
    ],
    ids=["several_marked", "another_species", "none_marked"],
)
async def test_a_length_frameshift_with_no_one_marked_strain_compares_nothing(
    monkeypatch: pytest.MonkeyPatch, members: list[GroupMember]
) -> None:
    length_site(monkeypatch, members)
    wire = served_snv(monkeypatch)

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "FRAMESHIFT"
    shift = result.frame_changes[0]
    assert (shift.reference_run, shift.variant_calls) == (None, None)
    assert wire.contexts == []


def constructed_plain() -> FrameChange:
    return FrameChange(
        source=GenomeSource(site="plasmodb", organism="pfalConstructed", seqid="s"),
        strand="+",
        start=10,
        end=40,
        frame_before=0,
        frame_after=1,
        shift=100,
        reference_residues=(5, 6),
        run=None,
        splice_pair=SplicePair(motif="GT..AG", donor=10, acceptor=40),
        steps_between=1,
    )


async def test_a_plain_intron_reads_nothing_further(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = served_snv(monkeypatch)
    site = constructed_site(monkeypatch)
    plain = constructed_plain()
    real = audit_strain_tools.check_length

    def with_a_plain_intron(*args: object) -> LengthCheck:
        return real(*args).model_copy(
            update={"verdict": "OTHER_FRAME", "frame_changes": [plain]}
        )

    monkeypatch.setattr(audit_strain_tools, "check_length", with_a_plain_intron)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert site.contigs
    assert result.dna.frame_changes == [plain]
    assert (wire.contexts, wire.searches, wire.read) == ([], [], [])


async def test_a_check_with_no_run_that_explains_a_shift_reads_no_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(site_id: str) -> None:
        raise AssertionError(site_id)

    monkeypatch.setattr(audit_tools, "ModelReads", refused)
    check = LengthCheck.not_checked().model_copy(
        update={"frame_changes": [constructed_plain()]}
    )
    dna = LengthDna.model_construct(
        strain_reference=StrainReference(gene=REFERENCE, organism=REFERENCE_ORGANISM)
    )

    assert await audit_tools.compared_check("plasmodb", check, dna) == check


async def test_details_are_read_once_for_a_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_site(monkeypatch)
    wire = served_snv(monkeypatch)
    real = audit_strain_tools.check_length

    def with_two_slips(*args: object) -> LengthCheck:
        check = real(*args)
        return check.model_copy(update={"frame_changes": check.frame_changes * 2})

    monkeypatch.setattr(audit_strain_tools, "check_length", with_two_slips)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert len(result.dna.frame_changes) == 2
    assert len(wire.contexts) == 1
    assert len(wire.searches) == 2


async def test_a_malformed_attribute_is_a_written_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed_site(monkeypatch)
    broken = SERVED_SNV.model_copy(
        update={"attributes": {**SERVED_SNV.attributes, "variant_type": {"url": 1}}}
    )
    install(monkeypatch, ServedVariants(WIRE.search, {SNV_ID: broken}))

    with pytest.raises(ToolError) as caught:
        await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert "input_value" not in str(caught.value)
    assert isinstance(caught.value.__cause__, WrittenParseError)
