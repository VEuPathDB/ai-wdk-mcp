import pytest
from tests._support.audit_site import AuditSite, Contig
from tests._support.proteins import PROTEIN, back_translate, row

from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.pseudogene import CdsPart

REFERENCE = "PCYM_1"
FLANK = 40000


def length_group(me: list[GeneRow], others: int = 8) -> list[GeneRow]:
    return [
        *me,
        row(REFERENCE, "Plasmodium cynomolgi strain M", 200),
        *(row(f"P{i}", f"Plasmodium species{i} X", 200) for i in range(others)),
    ]


PART_A = "PCYB_A"
PART_B = "PCYB_B"


def split_site(monkeypatch: pytest.MonkeyPatch) -> AuditSite:
    site = AuditSite(monkeypatch)
    first = back_translate(PROTEIN[:100]) + "TAA"
    second = back_translate(PROTEIN[100:]) + "TAA"
    contig = "C" * FLANK + first + "C" * 300 + second + "C" * FLANK
    a_start = FLANK + 1
    b_start = a_start + len(first) + 300
    organism = "Plasmodium cynomolgi strain B"
    a = row(PART_A, organism, 100, start=a_start)
    a = a.model_copy(update={"end": a_start + len(first) - 1})
    b = a.model_copy(
        update={"gene": PART_B, "start": b_start, "end": b_start + len(second) - 1}
    )
    site.rows = length_group([a, b])
    site.orthologs[PART_A] = site.rows
    site.proteins = {PART_A: PROTEIN[:100], PART_B: PROTEIN[100:], REFERENCE: PROTEIN}
    site.models[PART_A] = GeneModel(
        organism_abbrev="pcynB", cds=[CdsPart(start=a.start, end=a.end)]
    )
    site.models[PART_B] = GeneModel(
        organism_abbrev="pcynB", cds=[CdsPart(start=b.start, end=b.end)]
    )
    site.contigs["pcynB", a.sequence_id] = Contig.whole(contig)
    return site
