import json

import pytest
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
from veupathdb.errors import WDKError
from veupathdb.wdk import (
    WDKAnswer,
    WDKRecordInstance,
    WDKSearchConfig,
    WDKSearchResponse,
)

from veupathdb_mcp.audit import frameshift_inputs
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GroupMember, OrthologGroup
from veupathdb_mcp.audit.pseudogene import CdsPart
from veupathdb_mcp.tools import audit_tools
from veupathdb_mcp.tools.audit_strain_tools import audit_strain_model

PAD = 8000
SUFFIX = "s3be28bbe14_sample"
VARIANT = "Variant_chr1_8100"
ME = "PfNF54_040013300"
ME_ORGANISM = "Plasmodium falciparum NF54"
REFERENCE_ORGANISM = "Plasmodium falciparum 3D7"


def nf54_site(monkeypatch: pytest.MonkeyPatch) -> StrainSite:
    site = strain_site(monkeypatch, (MODEL_PROTEIN, REFERENCE_PROTEIN))
    strain, reference, *others = site.rows
    strain_dna = model_coding()
    reference_dna = reference_coding() + "TAA"
    strain_cds = CdsPart(start=PAD + 1, end=PAD + 3 * len(MODEL_PROTEIN) + 3)
    reference_cds = CdsPart(start=PAD + 1, end=PAD + len(reference_dna))
    site.rows = [
        strain.model_copy(update={"start": strain_cds.start, "end": strain_cds.end}),
        reference.model_copy(
            update={"start": reference_cds.start, "end": reference_cds.end}
        ),
        *others,
    ]
    site.orthologs[REFERENCE] = site.rows
    site.models[STRAIN] = GeneModel(organism_abbrev="pfalDd2", cds=[strain_cds])
    site.models[REFERENCE] = GeneModel(organism_abbrev="pfal3D7", cds=[reference_cds])
    flank = "C" * PAD
    site.contigs["pfalDd2", strain.sequence_id] = Contig.whole(
        flank + strain_dna + flank + flank
    )
    site.contigs["pfal3D7", reference.sequence_id] = Contig.whole(
        flank + reference_dna + flank
    )
    return site


class VariantWire:
    def __init__(self, records: dict[str, WDKRecordInstance]) -> None:
        self.records = records
        self.contexts: list[dict[str, str]] = []
        self.searches: list[WDKSearchConfig] = []
        self.read: list[str] = []
        self.refusal: WDKError | None = None

    async def get_search_details_with_params(
        self, record_type: str, search_name: str, context: dict[str, str]
    ) -> WDKSearchResponse:
        self.contexts.append(context)
        if self.refusal is not None:
            raise self.refusal
        return WDKSearchResponse.model_validate(
            {
                "searchData": {
                    "urlSegment": search_name,
                    "fullName": f"VariantQuestions.{search_name}",
                    "displayName": search_name,
                    "outputRecordClassName": record_type,
                    "paramNames": ["eda_sample_table_suffix", "WebServicesPath"],
                    "groups": [],
                    "parameters": [
                        {
                            "name": "eda_sample_table_suffix",
                            "type": "string",
                            "initialDisplayValue": SUFFIX,
                        },
                        {
                            "name": "WebServicesPath",
                            "type": "string",
                            "initialDisplayValue": "dflt",
                        },
                    ],
                },
                "validation": {"level": "DISPLAYABLE", "isValid": True},
            }
        )

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: dict[str, object],
    ) -> WDKAnswer:
        self.searches.append(search_config)
        return WDKAnswer.model_validate(
            {
                "records": [
                    record.model_dump(by_alias=True) for record in self.records.values()
                ],
                "meta": {
                    "totalCount": len(self.records),
                    "responseCount": len(self.records),
                    "displayTotalCount": len(self.records),
                    "viewTotalCount": len(self.records),
                    "displayViewTotalCount": len(self.records),
                    "recordClassName": record_type,
                    "attributes": [],
                    "tables": [],
                },
            }
        )

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
        return self.records[name]


def variant_record(name: str, rows: list[dict[str, str]]) -> WDKRecordInstance:
    return WDKRecordInstance.model_validate(
        {
            "displayName": name,
            "id": [
                {"name": "source_id", "value": name},
                {"name": "project_id", "value": "PlasmoDB"},
            ],
            "recordClassName": "VariantRecordClasses.VariantRecordClass",
            "attributes": {"indel_ref_allele": "A"},
            "tables": {"VariantStrains": rows},
        }
    )


def install_wire(
    monkeypatch: pytest.MonkeyPatch, records: dict[str, WDKRecordInstance]
) -> VariantWire:
    wire = VariantWire(records)
    monkeypatch.setattr(frameshift_inputs, "get_wdk_client", lambda site_id: wire)
    monkeypatch.setattr(frameshift_inputs, "get_strategy_api", lambda site_id: wire)
    return wire


async def test_a_strain_frameshift_reads_the_run_in_the_reference_strain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = nf54_site(monkeypatch)
    wire = install_wire(monkeypatch, {})

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    assert result.dna.verdict == "FRAMESHIFT"
    assert result.side == "NOT_JUDGED"
    [shift] = result.dna.frameshifts
    assert shift.run is not None
    assert (shift.run.unit, shift.run.bases) == ("A", 29)
    run = shift.reference_run
    assert run is not None
    assert (run.gene, run.bases) == (REFERENCE, 28)
    assert run.source.site == "plasmodb"
    assert run.source.organism == "pfal3D7"
    first = PAD + 1 + run_offset(reference_coding())
    assert (run.start, run.end) == (first, first + 27)
    assert site.models_read.count(REFERENCE) == 1
    assert wire.contexts == [{"organismSinglePick": json.dumps([REFERENCE_ORGANISM])}]


async def test_the_variant_search_reads_the_run_and_names_what_it_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nf54_site(monkeypatch)
    wire = install_wire(
        monkeypatch,
        {
            VARIANT: variant_record(
                VARIANT,
                [
                    {
                        "strain": "DD2_WTSI",
                        "genotype": "1",
                        "allele": "AA",
                        "depth": "49",
                        "read_frequency": "100.00",
                    }
                ],
            )
        },
    )

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    [shift] = result.dna.frameshifts
    calls = shift.variant_calls
    run = shift.reference_run
    assert calls is not None
    assert run is not None
    assert calls.answer == "INDEL_CALLED"
    assert calls.determinable
    assert (calls.site, calls.record_type, calls.search, calls.table) == (
        "plasmodb",
        "variation",
        "VariantsByLocation",
        "VariantStrains",
    )
    assert (calls.sample, calls.variants) == ("DD2_WTSI", [VARIANT])
    assert calls.homopolymer_bases == 29
    assert (calls.start, calls.end) == (run.start - 1, run.end + 1)
    assert wire.read == [VARIANT]
    [search] = wire.searches
    assert search.parameters == {
        "eda_sample_table_suffix": SUFFIX,
        "WebServicesPath": "dflt",
        "organismSinglePick": json.dumps([REFERENCE_ORGANISM]),
        "variation_sample_meta": '{"filters":[]}',
        "ReadFrequencyPercent": "20%",
        "MinPercentMinorAlleles": "0",
        "MinPercentIsolateCalls": "0",
        "sequenceId": run.source.seqid,
        "start_point": str(run.start - 1),
        "end_point": str(run.end + 1),
    }


async def test_no_call_over_a_long_run_cannot_be_determined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nf54_site(monkeypatch)
    install_wire(monkeypatch, {})

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    [shift] = result.dna.frameshifts
    assert shift.variant_calls is not None
    assert shift.variant_calls.answer == "NO_VARIANT_CALLED"
    assert not shift.variant_calls.determinable


@pytest.mark.parametrize("status", [404, 422])
async def test_a_site_with_no_calls_for_the_organism_gives_no_answer(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    nf54_site(monkeypatch)
    wire = install_wire(monkeypatch, {})
    wire.refusal = WDKError("refused", status=status)

    result = await audit_strain_model("plasmodb", STRAIN, REFERENCE)

    [shift] = result.dna.frameshifts
    assert shift.reference_run is not None
    assert shift.variant_calls is None


async def test_a_length_frameshift_compares_only_with_the_marked_reference_strain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = nf54_site(monkeypatch)
    wire = install_wire(monkeypatch, {})
    placed = site.rows[0]
    me = placed.model_copy(update={"gene": ME, "organism": ME_ORGANISM})
    site.rows = [me, *site.rows[1:]]
    site.proteins[ME] = MODEL_PROTEIN
    site.models[ME] = GeneModel(organism_abbrev="pfalNF54", cds=site.models[STRAIN].cds)
    site.contigs["pfalNF54", me.sequence_id] = site.contigs[
        "pfalDd2", placed.sequence_id
    ]
    site.orthologs[ME] = site.rows
    long = len(REFERENCE_PROTEIN)
    relatives = [row(f"K{i}", f"Plasmodium species{i} X", long) for i in range(8)]
    members = [
        GroupMember.of_row(other)
        for other in (
            row("PfHB3_1", "Plasmodium falciparum HB3", long),
            *relatives,
        )
    ]
    marked = GroupMember.of_row(site.rows[1]).model_copy(
        update={"reference_strain": True}
    )

    async def orthologs(site_id: str, gene: str) -> OrthologGroup:
        return OrthologGroup(
            gene=gene,
            members=[GroupMember.of_row(me), marked, *members],
        )

    monkeypatch.setattr("veupathdb_mcp.audit.served.orthologs_of", orthologs)

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "FRAMESHIFT"
    [shift] = result.frameshifts
    assert shift.source.organism == "pfalNF54"
    assert shift.reference_run is not None
    assert (shift.reference_run.gene, shift.reference_run.bases) == (REFERENCE, 28)
    assert wire.contexts == [{"organismSinglePick": json.dumps([REFERENCE_ORGANISM])}]
