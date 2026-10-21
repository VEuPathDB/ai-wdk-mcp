import asyncio
import json
import re
import threading
import time
from pathlib import Path
from typing import Literal

import httpx
import pytest
from fastmcp.exceptions import ToolError
from veupathdb.errors import WDKError
from veupathdb.jbrowse import GenomeIndexError, GenomeWindow, JBrowseError
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import gene_models, served
from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.pseudogene import CdsPart, PseudogeneCheck, ReferenceGene
from veupathdb_mcp.audit.selenocysteine import SecCheck, check_sec_stop
from veupathdb_mcp.audit.served import PseudogeneInputs, SelenoproteinInputs
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error
from veupathdb_mcp.tools import audit_tools

FIXTURES = Path(__file__).parent / "fixtures"
PIGA = "PF3D7_1032400"
NF54_PIGA = "PfNF54_100037200"
GT1_SELK = "TGGT1_316600"
ME49_SELK = "TGME49_316600"
SELK_PAD = served.SELENOPROTEIN_PAD + 3 * len("UG")

type Window = tuple[str, str, int, int]


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def reference_piga() -> ReferenceGene:
    ref = load("pfal3D7_piga.json")
    return ReferenceGene.model_validate(
        {
            "dna": ref["sequence"],
            "cds": [CdsPart(start=a, end=b) for a, b in ref["cds"]],
            "start": ref["start"],
            "end": ref["end"],
            "strand": ref["strand"],
        }
    )


async def piga_inputs(
    site_id: str, strain_gene: str, reference_gene: str
) -> PseudogeneInputs | ToolErrorPayload:
    if strain_gene != NF54_PIGA:
        return tool_error("VALIDATION_ERROR", f"{strain_gene} names no gene")
    strain = load("pfalNF54_piga.json")
    return PseudogeneInputs(
        reference=reference_piga(),
        strain_coding_dna=reverse_complement(str(strain["sequence"])),
    )


async def selk_inputs(
    site_id: str, gene: str, reference_gene: str
) -> SelenoproteinInputs | ToolErrorPayload:
    gt1, me49 = load("tgonGT1_selk.json"), load("tgonME49_selk.json")
    return SelenoproteinInputs(
        model_protein=str(gt1["model_protein"]),
        reference_protein=str(me49["reference_protein"]),
        dna=str(gt1["sequence"]),
        strand="+",
    )


async def test_the_pseudogene_tool_returns_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_tools, "pseudogene_inputs", piga_inputs)

    result = await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert result.verdict == "INTACT"
    assert result.strain_cds_length == result.reference_cds_length == 1386
    assert (result.strain_gene, result.reference_gene) == (NF54_PIGA, PIGA)


async def test_the_selenoprotein_tool_returns_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_tools, "selenoprotein_inputs", selk_inputs)

    result = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert result.verdict == "STOPS_AT_SEC"
    assert result.reference_tail == "UG"
    assert (result.gene, result.reference_gene) == (GT1_SELK, ME49_SELK)


async def test_a_refused_input_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_tools, "pseudogene_inputs", piga_inputs)

    with pytest.raises(ToolError, match="NOT_A_GENE names no gene"):
        await audit_tools.audit_pseudogene_call("plasmodb", "NOT_A_GENE", PIGA)


def strain_piga_row() -> GeneRow:
    return GeneRow(
        gene=NF54_PIGA,
        ortholog_group="OG8_0000001",
        protein_length=None,
        name="",
        product="phosphatidylinositol N-acetylglucosaminyltransferase subunit A",
        sequence_id="VBRF01000019.1",
        start=1063699,
        end=1065985,
        strand="-",
        pseudo=True,
        gene_type="pseudogene",
    )


def reference_piga_row() -> GeneRow:
    return strain_piga_row().model_copy(
        update={
            "gene": PIGA,
            "protein_length": 461,
            "name": "PIGA",
            "sequence_id": "Pf3D7_10_v3",
            "start": 1302298,
            "end": 1305315,
            "pseudo": False,
            "gene_type": "protein coding gene",
        }
    )


def gt1_selk_row() -> GeneRow:
    gt1 = load("tgonGT1_selk.json")
    return GeneRow(
        gene=GT1_SELK,
        ortholog_group="OG7_0000000",
        protein_length=131,
        name="",
        product="selenoprotein K",
        sequence_id=str(gt1["seqid"]),
        start=int(str(gt1["start"])) + SELK_PAD,
        end=int(str(gt1["end"])) - SELK_PAD,
        strand="+",
        pseudo=False,
        gene_type="protein coding gene",
    )


def me49_selk_row() -> GeneRow:
    me49 = load("tgonME49_selk.json")
    return gt1_selk_row().model_copy(
        update={
            "gene": ME49_SELK,
            "protein_length": 133,
            "sequence_id": str(me49["seqid"]),
            "start": int(str(me49["start"])),
            "end": int(str(me49["end"])),
        }
    )


class Site:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.rows = [
            strain_piga_row(),
            reference_piga_row(),
            gt1_selk_row(),
            me49_selk_row(),
        ]
        self.models = {
            PIGA: GeneModel(organism="pfal3D7", cds=reference_piga().cds),
            NF54_PIGA: GeneModel(organism="pfalNF54", cds=[]),
            GT1_SELK: GeneModel(organism="tgonGT1", cds=[]),
        }
        self.proteins = {
            GT1_SELK: str(load("tgonGT1_selk.json")["model_protein"]),
            ME49_SELK: str(load("tgonME49_selk.json")["reference_protein"]),
        }
        self.regions: dict[Window, str] = {}
        for name in ("pfal3D7_piga.json", "pfalNF54_piga.json", "tgonGT1_selk.json"):
            region = load(name)
            organism = name.split("_", 1)[0]
            key = (
                organism,
                str(region["seqid"]),
                int(str(region["start"])),
                int(str(region["end"])),
            )
            self.regions[key] = str(region["sequence"])
        self.windows: list[Window] = []
        self.models_read: list[str] = []
        self.refusal: Exception | None = None
        monkeypatch.setattr(served, "gene_rows", self.gene_rows)
        monkeypatch.setattr(served, "gene_model", self.gene_model)
        monkeypatch.setattr(served, "proteins_of", self.proteins_of)
        monkeypatch.setattr(served, "get_jbrowse_client", lambda site_id: self)
        monkeypatch.setattr(served, "GenomeReader", self.reader)

    async def gene_rows(self, site_id: str, gene_ids: list[str]) -> list[GeneRow]:
        return [row for row in self.rows if row.gene in gene_ids]

    async def gene_model(self, site_id: str, gene: str) -> GeneModel:
        self.models_read.append(gene)
        return self.models[gene]

    async def proteins_of(self, site_id: str, gene_ids: list[str]) -> dict[str, str]:
        return {gene: self.proteins[gene] for gene in gene_ids if gene in self.proteins}

    def reader(self, client: "Site") -> "Site":
        return client

    async def window(self, abbrev: str, seqid: str, start: int, end: int):
        self.windows.append((abbrev, seqid, start, end))
        if self.refusal is not None:
            raise self.refusal
        sequence = self.regions.get(
            (abbrev, seqid, start, end), "N" * (end - start + 1)
        )
        return GenomeWindow(seqid=seqid, start=start, sequence=sequence)


async def test_the_pseudogene_inputs_are_read_on_each_genes_own_strand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    result = await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert result.verdict == "INTACT"
    assert result.strain_cds_length == result.reference_cds_length == 1386
    assert result.residue_differences == 0
    assert site.windows == [
        ("pfal3D7", "Pf3D7_10_v3", 1302298, 1305315),
        ("pfalNF54", "VBRF01000019.1", 1060699, 1068985),
    ]


async def test_the_selenoprotein_inputs_pad_the_gene_past_the_reference_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    result = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert result.verdict == "STOPS_AT_SEC"
    assert result.after_model_end.startswith("*G*")
    assert site.windows == [("tgonGT1", "TGGT1_chrXI", 5359280, 5361636)]
    assert site.models_read == [GT1_SELK]


@pytest.mark.parametrize("strand", ["+", "-"])
async def test_the_selenoprotein_window_holds_a_long_tail_after_sec(
    monkeypatch: pytest.MonkeyPatch, strand: str
) -> None:
    site = Site(monkeypatch)
    tail = "U" + "G" * 400
    site.proteins[ME49_SELK] = "MKLVCGGGG" + tail
    gene = gt1_selk_row().model_copy(update={"strand": strand})
    site.rows[2] = gene

    await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    [(_, _, start, end)] = site.windows
    assert gene.start - start >= 3 * len(tail)
    assert end - gene.end >= 3 * len(tail)


async def test_a_reference_without_sec_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.proteins[ME49_SELK] = site.proteins[ME49_SELK].replace("U", "C")

    with pytest.raises(
        ToolError, match="TGME49_316600 has no selenocysteine on toxodb"
    ):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.models_read == []
    assert site.windows == []


async def test_a_pair_too_long_to_align_is_a_tool_error_naming_both_lengths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    reference = reference_piga_row()
    site.rows[1] = reference.model_copy(update={"end": reference.start + 39999})
    strain = strain_piga_row()
    strain_length = strain.end - strain.start + 1 + 2 * served.PSEUDOGENE_PAD

    with pytest.raises(ToolError, match=f"40000 .*{strain_length} "):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert 40000 * strain_length > served.PSEUDOGENE_MAX_CELLS
    assert site.models_read == []
    assert site.windows == []


async def test_the_longest_pair_under_the_limit_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    strain = strain_piga_row()
    strain_length = strain.end - strain.start + 1 + 2 * served.PSEUDOGENE_PAD
    reference = reference_piga_row()
    longest = served.PSEUDOGENE_MAX_CELLS // strain_length
    site.rows[1] = reference.model_copy(update={"end": reference.start + longest - 1})

    await served.pseudogene_inputs("plasmodb", NF54_PIGA, PIGA)

    assert site.windows[0] == (
        "pfal3D7",
        "Pf3D7_10_v3",
        reference.start,
        reference.start + longest - 1,
    )


async def test_a_site_that_does_not_answer_is_a_tool_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.refusal = httpx.ConnectTimeout("timed out")

    with pytest.raises(ToolError, match="plasmodb did not answer"):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)


async def test_an_unknown_gene_is_a_tool_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    with pytest.raises(ToolError, match="PF3D7_9999999 names no gene of plasmodb"):
        await audit_tools.audit_pseudogene_call("plasmodb", "PF3D7_9999999", PIGA)

    assert site.models_read == []
    assert site.windows == []


async def test_an_unknown_selenoprotein_reference_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    with pytest.raises(ToolError, match="TGME49_999999 names no gene of toxodb"):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, "TGME49_999999")

    assert site.windows == []


async def test_a_reference_without_cds_rows_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    site.models[PIGA] = GeneModel(organism="pfal3D7", cds=[])

    with pytest.raises(ToolError, match="PF3D7_1032400 has no CDS"):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert site.windows == []


async def test_a_gene_without_a_protein_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    del site.proteins[ME49_SELK]

    with pytest.raises(ToolError, match="TGME49_316600 has no protein on toxodb"):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.windows == []


@pytest.mark.parametrize(
    ("refusal", "named"),
    [
        (
            JBrowseError("GET", "https://qa.plasmodb.org/store", 500),
            "https://qa.plasmodb.org/store answered 500",
        ),
        (
            GenomeIndexError("the genome index of pfal3D7 has no sequence Pf3D7_10_v3"),
            "has no sequence Pf3D7_10_v3",
        ),
    ],
)
async def test_a_genome_read_refusal_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch, refusal: Exception, named: str
) -> None:
    site = Site(monkeypatch)
    site.refusal = refusal

    with pytest.raises(ToolError, match=named):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)


async def test_a_wdk_refusal_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    async def truncated(site_id: str, gene_ids: list[str]) -> list[GeneRow]:
        msg = "WDK GeneByLocusTag report served 1 records of a total of 2"
        raise WDKError(msg)

    monkeypatch.setattr(served, "gene_rows", truncated)

    with pytest.raises(ToolError, match="served 1 records of a total of 2"):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.windows == []


async def test_a_gene_record_without_an_organism_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)

    class Records:
        async def get_single_record(
            self,
            record_type: str,
            primary_key: list[dict[str, str]],
            *,
            attributes: list[str],
            tables: list[str],
        ) -> WDKRecordInstance:
            return WDKRecordInstance.model_validate(
                {"attributes": {"organismAbbrev": ""}, "tables": {}}
            )

    monkeypatch.setattr(served, "gene_model", gene_models.gene_model)
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: Records())

    with pytest.raises(ToolError, match="gene record of TGGT1_316600 on toxodb"):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.windows == []


def window_refused(gene: str, length: int) -> str:
    return re.escape(
        f"the {gene} window spans {length} bases; an audit reads at most "
        f"{served.AUDIT_MAX_WINDOW_BASES} bases of genome per window"
    )


async def test_a_selenoprotein_window_over_the_limit_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    gene = gt1_selk_row()
    site.rows[2] = gene.model_copy(
        update={"end": gene.start + served.AUDIT_MAX_WINDOW_BASES}
    )
    length = served.AUDIT_MAX_WINDOW_BASES + 1 + 2 * SELK_PAD

    with pytest.raises(ToolError, match=window_refused(GT1_SELK, length)):
        await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert site.models_read == []
    assert site.windows == []


async def test_a_selenoprotein_window_at_the_limit_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Site(monkeypatch)
    gene = gt1_selk_row()
    span = served.AUDIT_MAX_WINDOW_BASES - 2 * SELK_PAD
    site.rows[2] = gene.model_copy(update={"end": gene.start + span - 1})

    await served.selenoprotein_inputs("toxodb", GT1_SELK, ME49_SELK)

    [(_, _, start, end)] = site.windows
    assert end - start + 1 == served.AUDIT_MAX_WINDOW_BASES


@pytest.mark.parametrize(("over", "gene", "pad"), [(0, NF54_PIGA, 3000), (1, PIGA, 0)])
async def test_a_pseudogene_window_over_the_limit_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch, over: int, gene: str, pad: int
) -> None:
    site = Site(monkeypatch)
    reference = reference_piga_row()
    site.rows[1] = reference.model_copy(update={"end": reference.start + 99})
    row = site.rows[over]
    site.rows[over] = row.model_copy(
        update={"end": row.start + served.AUDIT_MAX_WINDOW_BASES}
    )
    length = served.AUDIT_MAX_WINDOW_BASES + 1 + 2 * pad

    with pytest.raises(ToolError, match=window_refused(gene, length)):
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)

    assert pad == 0 or 100 * length <= served.PSEUDOGENE_MAX_CELLS
    assert site.models_read == []
    assert site.windows == []


class Slots:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.lock = threading.Condition()
        self.release = threading.Event()
        self.running = 0
        self.peak = 0
        self.entered = 0
        self.threads: list[int] = []
        monkeypatch.setattr(audit_tools, "pseudogene_inputs", piga_inputs)
        monkeypatch.setattr(audit_tools, "selenoprotein_inputs", selk_inputs)
        monkeypatch.setattr(audit_tools, "check_pseudogene_call", self.pseudogene)
        monkeypatch.setattr(audit_tools, "check_sec_stop", self.sec_stop)

    def hold(self) -> None:
        with self.lock:
            self.threads.append(threading.get_ident())
            self.entered += 1
            self.running += 1
            self.peak = max(self.peak, self.running)
            self.lock.notify_all()
        self.release.wait(5)
        with self.lock:
            self.running -= 1

    def pseudogene(
        self, reference: ReferenceGene, strain: str, code: GeneticCode
    ) -> PseudogeneCheck:
        self.hold()
        return PseudogeneCheck(
            verdict="INTACT",
            reference_cds_length=1386,
            strain_cds_length=1386,
            covered=1386,
            premature_stops=[],
            residue_differences=0,
        )

    def sec_stop(
        self,
        model_protein: str,
        reference_protein: str,
        dna: str,
        strand: Literal["+", "-"],
        code: GeneticCode,
    ) -> SecCheck:
        self.hold()
        return check_sec_stop(model_protein, reference_protein, dna, strand, code)

    def wait_until_entered(self, count: int) -> bool:
        with self.lock:
            return self.lock.wait_for(lambda: self.entered >= count, timeout=5)

    async def until_entered(self, count: int) -> None:
        assert await asyncio.to_thread(self.wait_until_entered, count)
        await asyncio.sleep(0.05)


async def test_the_selenoprotein_check_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slots = Slots(monkeypatch)
    slots.release.set()

    result = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)

    assert result.verdict == "STOPS_AT_SEC"
    [thread] = slots.threads
    assert thread != threading.get_ident()


async def test_at_most_two_checks_run_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slots = Slots(monkeypatch)
    calls = [
        asyncio.create_task(audit_tools.audit_pseudogene_call("p", NF54_PIGA, PIGA)),
        asyncio.create_task(
            audit_tools.audit_selenoprotein_end("t", GT1_SELK, ME49_SELK)
        ),
        asyncio.create_task(audit_tools.audit_pseudogene_call("p", NF54_PIGA, PIGA)),
        asyncio.create_task(
            audit_tools.audit_selenoprotein_end("t", GT1_SELK, ME49_SELK)
        ),
    ]

    await slots.until_entered(2)
    entered_before_release = slots.entered
    slots.release.set()
    results = await asyncio.gather(*calls)

    assert entered_before_release == 2
    assert slots.peak == 2
    assert [r.verdict for r in results] == [
        "INTACT",
        "STOPS_AT_SEC",
        "INTACT",
        "STOPS_AT_SEC",
    ]


async def test_a_cancelled_call_keeps_its_slot_until_its_check_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slots = Slots(monkeypatch)
    first = [
        asyncio.create_task(audit_tools.audit_pseudogene_call("p", NF54_PIGA, PIGA))
        for _ in range(2)
    ]
    await slots.until_entered(2)
    first[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await first[0]

    later = asyncio.create_task(
        audit_tools.audit_selenoprotein_end("t", GT1_SELK, ME49_SELK)
    )
    await slots.until_entered(2)
    entered_before_release = slots.entered
    slots.release.set()
    await first[1]
    result = await later

    assert entered_before_release == 2
    assert slots.peak == 2
    assert result.verdict == "STOPS_AT_SEC"


def test_the_slots_hold_across_event_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = Slots(monkeypatch)
    checks.release.set()

    def short_check(
        reference: ReferenceGene, strain: str, code: GeneticCode
    ) -> PseudogeneCheck:
        time.sleep(0.02)
        return checks.pseudogene(reference, strain, code)

    monkeypatch.setattr(audit_tools, "check_pseudogene_call", short_check)

    async def contended() -> list[str]:
        results = await asyncio.gather(
            *(audit_tools.audit_pseudogene_call("p", NF54_PIGA, PIGA) for _ in range(3))
        )
        return [result.verdict for result in results]

    first = asyncio.run(contended())
    second = asyncio.run(contended())

    assert first == second == ["INTACT"] * 3
    assert checks.entered == 6
