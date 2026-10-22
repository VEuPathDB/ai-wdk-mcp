from collections.abc import Awaitable, Callable

import pytest
from pydantic import BaseModel
from scripts.record_audit_strain import StrainWire
from tests._support import anatomy_site
from tests._support.audit_fixtures import GT1_SELK, ME49_SELK, NF54_PIGA_ID, PIGA
from tests._support.audit_wire import (
    FIXTURES,
    install_genome,
    install_records,
    load_wire,
)
from tests._support.evidence_site import EvidenceSite, gene_record
from tests._support.intron_wire import Served, load_introns
from tests._support.length_site import PART_A, PART_B, split_site
from tests._support.piga_selk_site import Site
from tests._support.record_site import (
    install_recorded_records,
    install_store,
    load_records,
)
from tests._support.row_reads import serve_recorded_rows
from tests._support.strain_site import install_annotation
from veupathdb.wdk import StrategyAPI

from veupathdb_mcp.audit import genes, record_reads
from veupathdb_mcp.tools import (
    audit_anatomy_tools,
    audit_evidence_tools,
    audit_intron_tools,
    audit_strain_tools,
    audit_tools,
)

type Run = Callable[[], Awaitable[BaseModel]]
type Check = Callable[[pytest.MonkeyPatch], Run]


class DatasetCreatedError(AssertionError):
    pass


class DatasetTrap:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        monkeypatch.setattr(StrategyAPI, "create_dataset", self.refuse)
        monkeypatch.setattr(genes, "dataset_client", self.refuse)
        monkeypatch.setattr(record_reads, "dataset_client", self.refuse)

    def refuse(self, *args: object, **kwargs: object) -> None:
        self.calls.append(repr(args))
        raise DatasetCreatedError

    def armed(self) -> bool:
        return (
            StrategyAPI.create_dataset == self.refuse
            and genes.dataset_client == self.refuse
            and record_reads.dataset_client == self.refuse
        )


def gene_length(monkeypatch: pytest.MonkeyPatch) -> Run:
    wire = load_wire("pcynM_pkac_length.json")
    install_records(monkeypatch, wire)
    install_genome(monkeypatch, wire, "pcynM", "PcyM_07")
    serve_recorded_rows(monkeypatch, wire.gene_answers)
    return lambda: audit_tools.audit_gene_length("plasmodb", "PcyM_0736700")


def gene_split(monkeypatch: pytest.MonkeyPatch) -> Run:
    split_site(monkeypatch)
    return lambda: audit_tools.audit_gene_split("plasmodb", PART_A, PART_B)


def strain_model(monkeypatch: pytest.MonkeyPatch) -> Run:
    wire = StrainWire.model_validate_json(
        (FIXTURES / "strain_pcynM_pkac.json").read_text()
    )
    install_records(monkeypatch, wire)
    install_genome(monkeypatch, wire, "pcynM", "PcyM_07")
    install_annotation(monkeypatch, wire.annotation)
    serve_recorded_rows(
        monkeypatch, [*wire.gene_answers, *wire.row_answers], wire.protein_answers
    )
    return lambda: audit_strain_tools.audit_strain_model(
        "plasmodb", "PcyM_0736700", "PCYB_074210"
    )


def pseudogene_call(monkeypatch: pytest.MonkeyPatch) -> Run:
    Site(monkeypatch)
    return lambda: audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA_ID, PIGA)


def pseudogene_anatomy(monkeypatch: pytest.MonkeyPatch) -> Run:
    anatomy_site.AnatomySite(monkeypatch, anatomy_site.PIGA_FILE)
    return lambda: audit_anatomy_tools.audit_pseudogene_anatomy(
        "plasmodb", anatomy_site.NF54_PIGA, PIGA
    )


def selenoprotein_end(monkeypatch: pytest.MonkeyPatch) -> Run:
    Site(monkeypatch)
    return lambda: audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)


def gene_evidence(monkeypatch: pytest.MonkeyPatch) -> Run:
    site = EvidenceSite(monkeypatch, "plasmodb")
    site.records[PIGA] = gene_record("evidence_pfal3D7_piga.json")
    return lambda: audit_evidence_tools.audit_gene_evidence("plasmodb", PIGA)


def intron_support(monkeypatch: pytest.MonkeyPatch) -> Run:
    name = "introns_pcynM_pkac.json"
    Served(monkeypatch, load_introns(name), "introns_pcynM_pkac_proteins.json")
    return lambda: audit_intron_tools.audit_intron_support("plasmodb", "PcyM_0736700")


def recorded_intron(name: str, gene: str) -> Check:
    def check(monkeypatch: pytest.MonkeyPatch) -> Run:
        wire = load_records(name)
        install_recorded_records(monkeypatch, wire)
        install_store(monkeypatch, wire)
        return lambda: audit_intron_tools.audit_intron_support(wire.site, gene)

    return check


CHECKS: dict[str, Check] = {
    "audit_gene_length": gene_length,
    "audit_gene_split": gene_split,
    "audit_strain_model": strain_model,
    "audit_pseudogene_call": pseudogene_call,
    "audit_pseudogene_anatomy": pseudogene_anatomy,
    "audit_selenoprotein_end": selenoprotein_end,
    "audit_gene_evidence": gene_evidence,
    "audit_intron_support": intron_support,
    "Afu8g00850": recorded_intron("introns_afumAf293_afu8g00850.json.xz", "Afu8g00850"),
    "AGAP007279": recorded_intron("introns_agamPEST_agap007279.json.xz", "AGAP007279"),
    "TGME49_224540": recorded_intron(
        "introns_tgonME49_tgme49_224540.json.xz", "TGME49_224540"
    ),
    "AGAP003685": recorded_intron("introns_agamPEST_agap003685.json.xz", "AGAP003685"),
}


def test_every_chat_check_is_driven() -> None:
    assert {name for name in CHECKS if name.startswith("audit_")} == {
        "audit_gene_length",
        "audit_gene_split",
        "audit_strain_model",
        "audit_pseudogene_call",
        "audit_pseudogene_anatomy",
        "audit_selenoprotein_end",
        "audit_gene_evidence",
        "audit_intron_support",
    }


@pytest.mark.parametrize("name", sorted(CHECKS))
async def test_a_chat_check_completes_with_dataset_uploads_refused(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    run = CHECKS[name](monkeypatch)
    trap = DatasetTrap(monkeypatch)

    result = await run()

    assert type(result).model_validate(result.model_dump()) == result
    assert (trap.calls, trap.armed()) == ([], True)


async def test_the_trap_refuses_a_locus_tag_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trap = DatasetTrap(monkeypatch)

    with pytest.raises(DatasetCreatedError):
        await genes.locus_tag_answers("plasmodb", ["PF3D7_1032400"], ["organism"])

    assert len(trap.calls) == 1
