import asyncio
import threading
import time
from typing import Literal

import pytest
from tests._support.audit_fixtures import (
    GT1_SELK,
    ME49_SELK,
    NF54_PIGA,
    PIGA,
    piga_inputs,
    selk_inputs,
)
from tests._support.audit_site import own_id
from tests._support.proteins import PROTEIN, back_translate

from veupathdb_mcp.audit.codes import GeneticCode
from veupathdb_mcp.audit.gene_models import GeneModel, ModelRecord, ModelRow
from veupathdb_mcp.audit.length import DnaWindow, LengthCheck, check_length
from veupathdb_mcp.audit.pseudogene import CdsPart, PseudogeneCheck, ReferenceGene
from veupathdb_mcp.audit.selenocysteine import SecCheck, check_sec_stop
from veupathdb_mcp.audit.served import LengthDna, LengthInputs, LengthScreen
from veupathdb_mcp.tools import audit_tools


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


async def test_the_length_check_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads: list[int] = []

    def check(
        reference: str, models: list[str], window: DnaWindow, code: GeneticCode
    ) -> LengthCheck:
        threads.append(threading.get_ident())
        return check_length(reference, models, window, code)

    async def inputs(site_id: str, genes: list[str]) -> LengthInputs:
        return LengthInputs(
            screen=LengthScreen(
                gene_ids=[own_id(gene) for gene in genes],
                genes=genes,
                length_class="SHORT",
                ratio=0.7,
                group_median=200.0,
                group_copies=1.0,
                group_spread=0.0,
                organisms=10,
                reference_gene="R",
            ),
            dna=LengthDna(
                reference_protein=PROTEIN,
                model_proteins=[PROTEIN[:60] + PROTEIN[120:]],
                window=DnaWindow(
                    sequence="CCCC" + back_translate(PROTEIN) + "CCCC",
                    strand="+",
                    at_contig_edge=False,
                ),
                code=GeneticCode.STANDARD,
                code_inferred=True,
                models=[
                    ModelRecord(
                        gene=gene,
                        model=GeneModel(
                            organism_abbrev="pfal3D7",
                            cds=[CdsPart(start=5, end=604)],
                        ),
                        rows=[
                            ModelRow(
                                type=kind,
                                transcript_ids=frozenset({f"{gene}.1"}),
                                sequence_id="chr1",
                                strand="+",
                                gm_start=5,
                                gm_end=604,
                            )
                            for kind in ("CDS", "Exon")
                        ],
                    )
                    for gene in genes
                ],
            ),
        )

    monkeypatch.setattr(audit_tools, "length_inputs", inputs)
    monkeypatch.setattr(audit_tools, "check_length", check)

    result = await audit_tools.audit_gene_length("plasmodb", "ME")

    assert result.verdict == "GENOME_ENCODES"
    [thread] = threads
    assert thread != threading.get_ident()
