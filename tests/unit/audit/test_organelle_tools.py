import threading

import pytest
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from tests._support.audit_site import AuditSite, Contig, window_refused
from tests._support.organelle_fixtures import CYTB, organelle_site, recorded_site
from tests._support.proteins import PROTEIN, back_translate, row
from veupathdb.jbrowse import GenomeIndexError

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.organelle import OrganelleCheck, check_circular_join
from veupathdb_mcp.audit.organelle_inputs import OrganelleGeneAudit, first_coding_gene
from veupathdb_mcp.audit.pseudogene import CdsPart
from veupathdb_mcp.tools import audit_organelle_tools
from veupathdb_mcp.tools.audit_organelle_tools import audit_organelle_gene

REFERENCE = "PREF_MIT01"
STRAIN = "Plasmodium strain"
STRAIN_GENE = "PSTR_MT01"
MITO = "PSTR_MT"
LEFT = 500
SPACER = "C" * 2000


def tga_for_w(protein: str) -> str:
    return "".join("TGA" if a == "W" else back_translate(a) for a in protein)


def mito_site(
    monkeypatch: pytest.MonkeyPatch, coding: str = back_translate(PROTEIN) + "TAA"
) -> AuditSite:
    site = organelle_site(monkeypatch)
    reference = row(REFERENCE, "Plasmodium reference", len(PROTEIN), start=LEFT + 1)
    on_mito = row(STRAIN_GENE, STRAIN, 50, start=10).model_copy(
        update={"sequence_id": MITO}
    )
    site.rows = [reference, on_mito]
    site.proteins = {REFERENCE: PROTEIN}
    site.models[REFERENCE] = GeneModel(
        organism_abbrev="pref",
        cds=[CdsPart(start=reference.start, end=reference.end)],
    )
    site.models[STRAIN_GENE] = GeneModel(organism_abbrev="pstr", cds=[])
    site.contigs["pref", reference.sequence_id] = Contig.whole(
        "G" * LEFT + coding + SPACER
    )
    site.contigs["pstr", MITO] = Contig.whole(coding[301:] + SPACER + coding[:301])
    return site


async def test_a_gene_cut_by_the_contig_ends_is_served_split_at_the_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = mito_site(monkeypatch)

    result = await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert result.verdict == "SPLIT_AT_JOIN"
    assert (result.best_linear, result.best_circular) == (100, 200)
    assert (result.reference_length, result.contig_length) == (200, 2603)
    assert (result.organism, result.sequence_id) == (STRAIN, MITO)
    assert (result.reference_gene, result.overlap_bases) == (REFERENCE, 0)
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert (site.organisms_read, site.models_read) == ([STRAIN_GENE], [REFERENCE])
    assert site.windows == [
        ("pref", "PREF_MIT01_contig", LEFT + 1, LEFT + 603),
        ("pstr", MITO, 1, 2603),
    ]
    assert set(result.model_dump(by_alias=True)) == {
        "verdict",
        "bestLinear",
        "bestCircular",
        "referenceLength",
        "overlapBases",
        "overlapMismatches",
        "geneIds",
        "organism",
        "sequenceId",
        "referenceGene",
        "contigLength",
        "code",
        "codeInferred",
    }


async def test_the_check_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mito_site(monkeypatch)
    threads: list[int] = []

    def check(contig: str, reference: str, code: GeneticCode) -> OrganelleCheck:
        threads.append(threading.get_ident())
        return check_circular_join(contig, reference, code)

    monkeypatch.setattr(audit_organelle_tools, "check_circular_join", check)

    await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert len(threads) == 1
    assert threads[0] != threading.get_ident()


async def test_the_code_is_inferred_from_the_reference_gene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mito_site(monkeypatch, tga_for_w(PROTEIN) + "TAA")

    result = await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert (result.code, result.code_inferred) == (GeneticCode.UGA_TRYPTOPHAN, True)
    assert result.verdict == "SPLIT_AT_JOIN"


async def test_a_reference_without_cds_rows_reads_the_standard_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = mito_site(monkeypatch)
    site.models[REFERENCE] = GeneModel(organism_abbrev="pref", cds=[])

    result = await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, False)
    assert result.verdict == "SPLIT_AT_JOIN"


def test_the_abbreviation_is_read_from_the_first_coding_gene_of_the_sequence() -> None:
    first = row("PSTR_MT01", STRAIN, 100, start=900)
    pseudo = row("PSTR_MT00", STRAIN, 100, start=10).model_copy(update={"pseudo": True})
    unknown = row("PSTR_MT02", STRAIN, 100, start=50).model_copy(
        update={"pseudo": None}
    )
    rrna = row("PSTR_MT03:rRNA", STRAIN, None, start=5).model_copy(
        update={"gene_type": "ncRNA gene"}
    )

    assert first_coding_gene([first, pseudo, unknown, rrna]) == unknown
    assert first_coding_gene([first, pseudo]) == first
    assert first_coding_gene([pseudo]) is None
    assert first_coding_gene([]) is None


@pytest.mark.parametrize(
    ("organism", "sequence_id"),
    [("Plasmodium other", MITO), (STRAIN, "PSTR_API")],
)
async def test_a_sequence_without_a_coding_gene_of_the_organism_is_refused(
    monkeypatch: pytest.MonkeyPatch, organism: str, sequence_id: str
) -> None:
    site = mito_site(monkeypatch)

    with pytest.raises(
        ToolError,
        match=f"{sequence_id} holds no protein-coding gene of {organism} on plasmodb",
    ):
        await audit_organelle_gene("plasmodb", organism, sequence_id, REFERENCE)

    assert site.models_read == []
    assert site.windows == []


async def test_a_contig_over_the_window_limit_is_refused_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = mito_site(monkeypatch)
    length = served.AUDIT_MAX_WINDOW_BASES + 1
    site.contigs["pstr", MITO] = Contig(start=1, sequence="", length=length)

    with pytest.raises(ToolError, match=window_refused(MITO, length)):
        await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert site.lengths_read == [("pstr", MITO)]
    assert (site.organisms_read, site.models_read) == ([STRAIN_GENE], [])
    assert site.windows == []


async def test_a_reference_longer_than_half_the_contig_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = mito_site(monkeypatch)
    site.contigs["pstr", MITO] = Contig.whole("G" * 600 + "C" * 599)

    with pytest.raises(
        ToolError,
        match=(
            "PREF_MIT01 against PSTR_MT: the reference codes 200 residues, 600 "
            "bases, more than half of the 1199-base circle; a turn by half "
            "cannot place it whole"
        ),
    ):
        await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert (site.organisms_read, site.models_read) == ([STRAIN_GENE], [REFERENCE])


async def test_a_reference_span_over_the_window_limit_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = mito_site(monkeypatch)
    reference = site.rows[0]
    end = reference.start + served.AUDIT_MAX_WINDOW_BASES
    site.rows[0] = reference.model_copy(update={"end": end})
    length = served.AUDIT_MAX_WINDOW_BASES + 1

    with pytest.raises(ToolError, match=window_refused(REFERENCE, length)):
        await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert site.lengths_read == []
    assert site.windows == []


async def test_an_unknown_reference_gene_is_a_tool_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = mito_site(monkeypatch)

    with pytest.raises(ToolError, match="PREF_MIT99 names no gene of plasmodb"):
        await audit_organelle_gene("plasmodb", STRAIN, MITO, "PREF_MIT99")

    assert site.windows == []


async def test_a_reference_without_a_protein_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = mito_site(monkeypatch)
    site.proteins = {}

    with pytest.raises(ToolError, match="PREF_MIT01 has no protein on plasmodb"):
        await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert site.lengths_read == []
    assert site.windows == []


async def test_a_sequence_the_genome_index_lacks_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = mito_site(monkeypatch)

    async def unindexed(abbrev: str, seqid: str) -> int:
        msg = f"the genome index of {abbrev} has no sequence {seqid}"
        raise GenomeIndexError(msg)

    monkeypatch.setattr(site, "sequence_length", unindexed)

    with pytest.raises(ToolError, match="the genome index of pstr has no sequence"):
        await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)

    assert site.windows == []


@pytest.mark.parametrize(
    ("organism", "sequence_id", "abbrev", "expected"),
    [
        ("NF54", "CM019798.1", "pfalNF54", ("SPLIT_AT_JOIN", 87, 0, 274, 376)),
        ("7G8 2019", "CM019769.1", "pfal7G8-2019", ("SPLIT_AT_JOIN", 127, 0, 248, 376)),
        ("7G8", "Pf7G8_MT", "pfal7G8", ("SPLIT_AT_JOIN", 127, 1, 272, 376)),
        ("3D7", "Pf3D7_MIT_v3", "pfal3D7", ("INTACT_ON_THE_LINE", 0, 0, 376, 376)),
        ("SN01", "PfSN01_MT", "pfalSN01", ("NOT_FOUND", 127, 0, 291, 291)),
    ],
)
async def test_the_recorded_mitochondria_are_read_by_organism_name(
    monkeypatch: pytest.MonkeyPatch,
    organism: str,
    sequence_id: str,
    abbrev: str,
    expected: tuple[str, int, int, int, int],
) -> None:
    site, reports = recorded_site(monkeypatch)
    name = f"Plasmodium falciparum {organism}"

    result = await audit_organelle_gene("plasmodb", name, sequence_id, CYTB)

    assert (
        result.verdict,
        result.overlap_bases,
        result.overlap_mismatches,
        result.best_linear,
        result.best_circular,
    ) == expected
    assert (result.organism, result.code, result.code_inferred) == (
        name,
        GeneticCode.STANDARD,
        True,
    )
    assert reports.organisms == [name]
    assert site.windows[0] == ("pfal3D7", "Pf3D7_MIT_v3", 3492, 4622)
    assert site.windows[1][:3] == (abbrev, sequence_id, 1)
    assert site.models_read[-1] == CYTB


async def test_an_organelle_answer_whose_gene_ids_name_another_gene_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mito_site(monkeypatch)
    served = (
        await audit_organelle_gene("plasmodb", STRAIN, MITO, REFERENCE)
    ).model_dump()

    with pytest.raises(ValidationError, match="geneIds resolve to"):
        OrganelleGeneAudit.model_validate({**served, "reference_gene": "OTHER"})
