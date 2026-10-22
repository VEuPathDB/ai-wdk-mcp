import pytest
from tests._support.audit_fixtures import (
    GT1_SELK,
    ME49_SELK,
    NF54_PIGA,
    NF54_PIGA_ID,
    PIGA,
    load,
    load_protein,
    reference_piga,
    reference_protein,
)
from tests._support.audit_site import AuditSite

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.pseudogene import CdsPart

SELK_PAD = served.SELENOPROTEIN_PAD + 3 * len("UG")


def strain_piga_row() -> GeneRow:
    return GeneRow(
        gene=NF54_PIGA_ID,
        organism="Plasmodium falciparum NF54",
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
            "organism": "Plasmodium falciparum 3D7",
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
        organism="Toxoplasma gondii GT1",
        ortholog_group="OG7_0000000",
        protein_length=131,
        name="",
        product="selenoprotein K",
        sequence_id=gt1.seqid,
        start=gt1.start + SELK_PAD,
        end=gt1.end - SELK_PAD,
        strand="+",
        pseudo=False,
        gene_type="protein coding gene",
    )


def me49_selk_row() -> GeneRow:
    me49 = load("tgonME49_selk.json")
    return gt1_selk_row().model_copy(
        update={
            "gene": ME49_SELK,
            "organism": "Toxoplasma gondii ME49",
            "protein_length": 133,
            "sequence_id": me49.seqid,
            "start": me49.start,
            "end": me49.end,
        }
    )


class Site(AuditSite):
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(monkeypatch)
        self.rows = [
            strain_piga_row(),
            reference_piga_row(),
            gt1_selk_row(),
            me49_selk_row(),
        ]
        self.aliases = {NF54_PIGA: [NF54_PIGA_ID]}
        gt1, me49 = gt1_selk_row(), me49_selk_row()
        self.models = {
            PIGA: GeneModel(organism_abbrev="pfal3D7", cds=reference_piga().cds),
            NF54_PIGA_ID: GeneModel(organism_abbrev="pfalNF54", cds=[]),
            GT1_SELK: GeneModel(
                organism_abbrev="tgonGT1",
                cds=[CdsPart(start=gt1.start, end=gt1.end)],
            ),
            ME49_SELK: GeneModel(
                organism_abbrev="tgonME49",
                cds=[CdsPart(start=me49.start, end=me49.end)],
            ),
        }
        self.proteins = {
            GT1_SELK: load_protein("tgonGT1_selk.json").model_protein,
            ME49_SELK: reference_protein("tgonME49_selk.json"),
        }
        for name in ("pfal3D7_piga.json", "pfalNF54_piga.json", "tgonGT1_selk.json"):
            region = load(name)
            organism = name.split("_", 1)[0]
            key = (organism, region.seqid, region.start, region.end)
            self.regions[key] = region.sequence
