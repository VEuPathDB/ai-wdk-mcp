import asyncio
import threading

import pytest
from fastmcp.exceptions import ToolError
from tests._support.audit_site import own_id
from tests._support.missing_site import EXAMPLE, GT1, gene, tga_for_w
from tests._support.proteins import PROTEIN, back_translate
from veupathdb.errors import DataParsingError

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.missing import Anchor, Anchors, MissingScan, scan_for_protein
from veupathdb_mcp.audit.missing_inputs import AnchoredDna, MissingInputs
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error
from veupathdb_mcp.tools import audit_missing_tools, audit_tools

CONTIG = "TGGT1_chrVIIb"
WINDOW_START = 4147900
CODING_START = WINDOW_START + 3003


def anchors() -> Anchors:
    return Anchors(
        left=Anchor(
            neighbour="TGARI_257070",
            gene="TGGT1_257070",
            sequence_id=CONTIG,
            start=4150000,
            end=4150899,
            strand="+",
        ),
        right=Anchor(
            neighbour="TGARI_257100",
            gene="TGGT1_257100",
            sequence_id=CONTIG,
            start=4176004,
            end=4176903,
            strand="-",
        ),
    )


def in_gt1(name: str, start: int) -> GeneRow:
    return gene(name, start, organism=GT1, sequence_id=CONTIG)


class Served:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, inputs: MissingInputs | ToolErrorPayload
    ) -> None:
        self.inputs = inputs
        self.read = asyncio.Event()
        monkeypatch.setattr(audit_missing_tools, "missing_inputs", self.missing)

    async def missing(
        self, site_id: str, example_gene: str, absent_organism: str
    ) -> MissingInputs | ToolErrorPayload:
        self.read.set()
        return self.inputs


def encoded(
    genes: list[GeneRow],
    sequence: str | None = None,
    code: GeneticCode = GeneticCode.STANDARD,
) -> MissingInputs:
    filler = "C" * 3000
    coding = reverse_complement("TAA" + back_translate(PROTEIN) + "TAA")
    return MissingInputs(
        gene_ids=[own_id(EXAMPLE)],
        protein=PROTEIN,
        annotated_members=[],
        dna=AnchoredDna(
            anchors=anchors(),
            sequence=filler + coding + filler if sequence is None else sequence,
            start=WINDOW_START,
            genes=genes,
            code=code,
            code_inferred=True,
        ),
    )


ANCHOR_ROWS = [in_gt1("TGGT1_257070", 4150000), in_gt1("TGGT1_257100", 4176004)]


async def test_a_gene_the_dna_holds_with_no_model_is_unannotated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Served(monkeypatch, encoded(ANCHOR_ROWS))

    result = await audit_missing_tools.audit_missing_gene("toxodb", EXAMPLE, GT1)

    assert result.verdict == "IN_DNA_UNANNOTATED"
    assert result.located is not None
    assert (result.located.found, result.located.windows, result.located.span) == (
        19,
        19,
        (CODING_START, CODING_START + 599),
    )
    assert result.open_frame is not None
    assert (result.open_frame.length, result.open_frame.identical) == (200, 200)
    assert (result.example_gene, result.absent_organism) == (EXAMPLE, GT1)
    assert (result.example_length, result.anchors, result.overlapping) == (
        200,
        anchors(),
        [],
    )
    assert (result.stops, result.intact_frame) == ([], True)
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)


async def test_the_inferred_code_reads_the_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filler = "C" * 3000
    dna = filler + "TAA" + tga_for_w(PROTEIN) + "TAA" + filler
    Served(monkeypatch, encoded(ANCHOR_ROWS, dna, GeneticCode.UGA_TRYPTOPHAN))

    result = await audit_missing_tools.audit_missing_gene("toxodb", EXAMPLE, GT1)

    assert result.verdict == "IN_DNA_UNANNOTATED"
    assert result.open_frame is not None
    assert (result.open_frame.length, result.open_frame.identical) == (200, 200)
    assert (result.stops, result.intact_frame) == ([], True)
    assert result.model_dump(by_alias=True, mode="json")["code"] == "uga_tryptophan"


async def test_a_pseudogene_over_the_span_is_another_model_named_pseudo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pseudogene = in_gt1("TGGT1_257091", CODING_START - 100).model_copy(
        update={"pseudo": True, "gene_type": "pseudogene", "protein_length": None}
    )
    Served(monkeypatch, encoded([*ANCHOR_ROWS, pseudogene]))

    result = await audit_missing_tools.audit_missing_gene("toxodb", EXAMPLE, GT1)

    assert result.verdict == "IN_DNA_OTHER_MODEL"
    assert result.model_dump(by_alias=True)["overlapping"] == [
        {
            "gene": "TGGT1_257091",
            "product": "conserved protein",
            "orthologGroup": "OG8_0000001",
            "proteinLength": None,
            "start": CODING_START - 100,
            "end": CODING_START + 799,
            "strand": "+",
            "pseudo": True,
            "geneType": "pseudogene",
        }
    ]


async def test_no_anchors_is_no_synteny_and_no_genome_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Served(
        monkeypatch,
        MissingInputs(
            gene_ids=[own_id(EXAMPLE)],
            protein=PROTEIN,
            annotated_members=[],
            dna=None,
        ),
    )

    result = await audit_missing_tools.audit_missing_gene("toxodb", EXAMPLE, GT1)

    assert result.verdict == "NO_SYNTENY"
    assert (result.anchors, result.located, result.open_frame) == (None, None, None)
    assert (result.overlapping, result.example_length) == (None, 200)
    assert (result.stops, result.intact_frame) == (None, None)
    assert (result.code, result.code_inferred) == (None, False)
    assert result.annotated_members == []


async def test_members_of_the_group_in_the_absent_genome_are_annotated_in_genome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = in_gt1("TGGT1_999999", 100000).model_copy(
        update={"sequence_id": "TGGT1_chrX"}
    )
    Served(
        monkeypatch,
        MissingInputs(
            gene_ids=[own_id(EXAMPLE)],
            protein=PROTEIN,
            annotated_members=[member],
            dna=None,
        ),
    )

    result = await audit_missing_tools.audit_missing_gene("toxodb", EXAMPLE, GT1)

    assert result.verdict == "ANNOTATED_IN_GENOME"
    assert result.model_dump(by_alias=True)["annotatedMembers"] == [
        {"gene": "TGGT1_999999", "sequenceId": "TGGT1_chrX", "start": 100000}
    ]
    assert (result.anchors, result.located, result.overlapping) == (None, None, None)
    assert (result.code, result.code_inferred) == (None, False)


async def test_dna_without_the_protein_is_not_in_dna(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Served(monkeypatch, encoded(ANCHOR_ROWS, "C" * 9000))

    result = await audit_missing_tools.audit_missing_gene("toxodb", EXAMPLE, GT1)

    assert result.verdict == "NOT_IN_DNA"
    assert result.located is not None
    assert (result.located.found, result.located.span, result.open_frame) == (
        0,
        None,
        None,
    )
    assert (result.overlapping, result.stops, result.intact_frame) == ([], [], None)


async def test_a_refused_input_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Served(monkeypatch, tool_error("VALIDATION_ERROR", "X names no gene"))

    with pytest.raises(ToolError, match="X names no gene"):
        await audit_missing_tools.audit_missing_gene("toxodb", "X", GT1)


async def test_a_site_error_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing(
        site_id: str, example_gene: str, absent_organism: str
    ) -> MissingInputs:
        msg = "WDK GenesByLocation report served 3 records of 9"
        raise DataParsingError(msg)

    monkeypatch.setattr(audit_missing_tools, "missing_inputs", failing)

    with pytest.raises(ToolError, match="served 3 records of 9"):
        await audit_missing_tools.audit_missing_gene("toxodb", EXAMPLE, GT1)


async def test_the_scan_runs_in_an_audit_slot_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served = Served(monkeypatch, encoded(ANCHOR_ROWS))
    threads: list[int] = []
    scanned = threading.Event()

    def scan(
        protein: str, window: str, window_start: int, code: GeneticCode
    ) -> MissingScan:
        threads.append(threading.get_ident())
        scanned.set()
        return scan_for_protein(protein, window, window_start, code)

    monkeypatch.setattr(audit_missing_tools, "scan_for_protein", scan)
    slots = audit_tools.audit_slots()
    await slots.acquire()
    await slots.acquire()
    call = asyncio.create_task(
        audit_missing_tools.audit_missing_gene("toxodb", EXAMPLE, GT1)
    )
    await served.read.wait()
    started = await asyncio.to_thread(scanned.wait, 0.2)
    slots.release()
    slots.release()
    result = await call

    assert started is False
    assert result.verdict == "IN_DNA_UNANNOTATED"
    assert threads != [threading.get_ident()]
    assert len(threads) == 1
