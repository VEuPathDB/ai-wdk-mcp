import re

import pytest
from tests._support.audit_site import own_id, window_refused
from tests._support.missing_site import (
    ARI,
    EXAMPLE,
    GT1,
    MissingSite,
    gene,
    tga_for_w,
)
from tests._support.proteins import PROTEIN, back_translate

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.missing import Anchor, Anchors
from veupathdb_mcp.audit.missing_inputs import (
    AnchoredDna,
    MissingInputs,
    missing_inputs,
)
from veupathdb_mcp.audit.pseudogene import CdsPart
from veupathdb_mcp.audit.served import AUDIT_MAX_WINDOW_BASES
from veupathdb_mcp.tool_errors import ToolErrorPayload
from veupathdb_mcp.tools.audit_missing_tools import audit_missing_gene
from veupathdb_mcp.tools.refusals import payload_or_error

START = 829583
CONTIG = "TGGT1_chrVIIb"
WINDOW = "ACGT" * 7776 + "AC"


def in_gt1(name: str, group: str, start: int, sequence_id: str = CONTIG) -> GeneRow:
    return gene(name, start, organism=GT1, sequence_id=sequence_id, group=group)


def arranged(monkeypatch: pytest.MonkeyPatch) -> MissingSite:
    site = MissingSite(monkeypatch)
    site.rows = [
        gene("TGARI_257070", START - 6000, group="OG8_5000001"),
        gene("TGARI_257080", START - 3000, group="OG8_5000002"),
        gene(EXAMPLE, START, group="OG8_0003979").model_copy(
            update={"end": START + 602}
        ),
        gene("TGARI_257100", START + 3000, group="OG8_5000003"),
        in_gt1("TGGT1_257070", "OG8_5000001", 4150000),
        in_gt1("TGGT1_257080", "OG8_5000002", 4160000),
        in_gt1("TGGT1_999999", "OG8_5000002", 100000, "TGGT1_chrX"),
        in_gt1("TGGT1_257100", "OG8_5000003", 4176004),
        in_gt1("TGGT1_257110", "OG8_5000004", 4179000),
        in_gt1("TGGT1_257200", "OG8_5000005", 4190000),
    ]
    site.proteins = {EXAMPLE: PROTEIN}
    site.models = {
        EXAMPLE: GeneModel(
            organism_abbrev="tgonARI", cds=[CdsPart(start=START, end=START + 602)]
        ),
        "TGGT1_257070": GeneModel(organism_abbrev="tgonGT1", cds=[]),
    }
    site.contigs = {
        "KQ976331": (START, back_translate(PROTEIN) + "TAA"),
        CONTIG: (4147899, WINDOW),
    }
    return site


def refusal(result: MissingInputs | ToolErrorPayload) -> str:
    match result:
        case ToolErrorPayload(message=message):
            return message
        case MissingInputs():
            raise AssertionError(result)


async def test_the_reader_reads_the_dna_between_the_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)

    result = await missing_inputs("toxodb", EXAMPLE, GT1)

    left = Anchor.model_validate(
        {**site.rows[4].model_dump(), "neighbour": "TGARI_257070"}
    )
    right = Anchor.model_validate(
        {**site.rows[7].model_dump(), "neighbour": "TGARI_257100"}
    )
    assert result == MissingInputs(
        gene_ids=[own_id(EXAMPLE)],
        protein=PROTEIN,
        annotated_members=[],
        dna=AnchoredDna(
            anchors=Anchors(left=left, right=right),
            sequence=WINDOW,
            start=4147899,
            genes=[site.rows[4], site.rows[5], site.rows[7], site.rows[8]],
            code=GeneticCode.STANDARD,
            code_inferred=True,
        ),
    )
    assert site.genomes_read == [GT1, ARI]
    assert site.rows_read == [[EXAMPLE]]
    assert (site.models_read, site.organisms_read) == ([EXAMPLE], ["TGGT1_257070"])
    assert site.windows == [
        ("tgonARI", "KQ976331", START, START + 602),
        ("tgonGT1", CONTIG, 4147899, 4179004),
    ]


async def test_the_code_is_inferred_from_the_example_gene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)
    site.contigs["KQ976331"] = (START, tga_for_w(PROTEIN) + "TAA")

    result = payload_or_error(await missing_inputs("toxodb", EXAMPLE, GT1))

    assert result.dna is not None
    assert (result.dna.code, result.dna.code_inferred) == (
        GeneticCode.UGA_TRYPTOPHAN,
        True,
    )


async def test_a_cds_no_code_explains_reads_with_the_standard_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)
    site.contigs["KQ976331"] = (START, "C" * 603)

    result = payload_or_error(await missing_inputs("toxodb", EXAMPLE, GT1))

    assert result.dna is not None
    assert (result.dna.code, result.dna.code_inferred) == (GeneticCode.STANDARD, False)


async def test_no_anchor_pair_reads_no_genome(monkeypatch: pytest.MonkeyPatch) -> None:
    site = arranged(monkeypatch)
    site.rows = site.rows[:7]

    result = await missing_inputs("toxodb", EXAMPLE, GT1)

    assert result == MissingInputs(
        gene_ids=[own_id(EXAMPLE)], protein=PROTEIN, annotated_members=[], dna=None
    )
    assert (site.models_read, site.windows) == ([], [])


async def test_a_member_of_the_example_group_in_the_absent_genome_stops_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)
    member = in_gt1("TGGT1_999998", "OG8_0003979", 500000, "TGGT1_chrX")
    site.rows.append(member)

    result = await missing_inputs("toxodb", EXAMPLE, GT1)

    assert result == MissingInputs(
        gene_ids=[own_id(EXAMPLE)],
        protein=PROTEIN,
        annotated_members=[member],
        dna=None,
    )
    assert site.genomes_read == [GT1]
    assert (site.models_read, site.windows) == ([], [])


async def test_an_example_without_an_orthology_group_checks_no_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)
    site.rows[2] = site.rows[2].model_copy(update={"ortholog_group": "OGR8r1_0000001"})
    site.rows.append(in_gt1("TGGT1_999998", "OGR8r1_0000001", 500000, "TGGT1_chrX"))

    result = payload_or_error(await missing_inputs("toxodb", EXAMPLE, GT1))

    assert result.annotated_members is None
    assert result.dna is not None


async def test_an_unknown_gene_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    site = arranged(monkeypatch)

    result = await missing_inputs("toxodb", "TGARI_000000", GT1)

    assert refusal(result) == "TGARI_000000 names no gene of toxodb"
    assert site.genomes_read == []


async def test_the_example_organism_is_not_the_absent_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arranged(monkeypatch)

    result = await missing_inputs("toxodb", EXAMPLE, ARI)

    assert refusal(result) == (
        f"{EXAMPLE} is a gene of {ARI}; the absent organism is another one"
    )


async def test_a_protein_under_two_windows_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)
    site.proteins = {EXAMPLE: PROTEIN[:39]}

    result = await missing_inputs("toxodb", EXAMPLE, GT1)

    assert refusal(result) == (
        f"the protein of {EXAMPLE} on toxodb has 39 residues; "
        "the check reads proteins of at least 40"
    )
    assert site.genomes_read == []


async def test_a_gene_without_a_protein_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)
    site.proteins = {}

    result = await missing_inputs("toxodb", EXAMPLE, GT1)

    assert refusal(result) == f"{EXAMPLE} has no protein on toxodb"


async def test_an_example_over_the_window_limit_is_refused_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)
    site.rows[2] = site.rows[2].model_copy(
        update={"end": START + AUDIT_MAX_WINDOW_BASES}
    )

    result = await missing_inputs("toxodb", EXAMPLE, GT1)

    assert re.fullmatch(
        window_refused(EXAMPLE, AUDIT_MAX_WINDOW_BASES + 1), refusal(result)
    )
    assert (site.genomes_read, site.models_read, site.windows) == ([], [], [])


async def test_a_translocated_member_is_annotated_in_genome_beside_a_degenerate_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = arranged(monkeypatch)
    copy = "C" * 20000 + back_translate(PROTEIN[:130]) + "C" * 12000
    site.contigs[CONTIG] = (4147899, copy)

    unchecked = await audit_missing_gene("toxodb", EXAMPLE, GT1)
    site.rows.append(in_gt1("TGGT1_999998", "OG8_0003979", 500000, "TGGT1_chrX"))
    site.windows.clear()
    checked = await audit_missing_gene("toxodb", EXAMPLE, GT1)

    assert unchecked.located is not None
    assert (unchecked.verdict, unchecked.located.found) == ("IN_DNA_UNANNOTATED", 13)
    assert checked.verdict == "ANNOTATED_IN_GENOME"
    assert checked.model_dump(by_alias=True)["annotatedMembers"] == [
        {"gene": "TGGT1_999998", "sequenceId": "TGGT1_chrX", "start": 500000}
    ]
    assert site.windows == []
