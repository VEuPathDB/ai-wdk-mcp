import pytest
from tests._support.audit_site import AuditSite, Contig
from tests._support.proteins import back_translate, row

from veupathdb_mcp.audit import strain_inputs
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.pseudogene import CdsPart

STRAIN = "PfDd2_1"
REFERENCE = "PF3D7_1"
DD2 = "Plasmodium falciparum Dd2"
PF3D7 = "Plasmodium falciparum 3D7"
FLANK = 40000
INSERT = "ACDEFGHIKLMNPQRSTVWY" * 2


class StrainSite(AuditSite):
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(monkeypatch)
        self.orthologs_read: list[str] = []
        monkeypatch.setattr(strain_inputs, "orthologs_of", self.orthologs_of)

    async def orthologs_of(self, site_id: str, gene: str) -> list[GeneRow]:
        self.orthologs_read.append(gene)
        return await super().orthologs_of(site_id, gene)


def coding_parts(protein: str, intron: str = "") -> list[str]:
    if not intron:
        return [back_translate(protein) + "TAA"]
    return [back_translate(protein[:60]), back_translate(protein[60:]) + "TAA"]


def strain_site(
    monkeypatch: pytest.MonkeyPatch,
    proteins: tuple[str, str],
    *,
    intron: str = "",
    left: int = FLANK,
    relatives: int = 8,
) -> StrainSite:
    strain_protein, reference_protein = proteins
    parts = coding_parts(strain_protein, intron)
    gene = intron.join(parts)
    start = left + 1
    end = left + len(gene)
    cds = [CdsPart(start=start, end=start + len(parts[0]) - 1)]
    if intron:
        cds.append(CdsPart(start=end - len(parts[1]) + 1, end=end))
    site = StrainSite(monkeypatch)
    strain = row(STRAIN, DD2, len(strain_protein), start=start)
    site.rows = [
        strain.model_copy(update={"end": end}),
        row(REFERENCE, PF3D7, len(reference_protein)),
        *(row(f"P{i}", f"Plasmodium species{i} X", 200) for i in range(relatives)),
    ]
    site.orthologs[REFERENCE] = site.rows
    site.proteins = {STRAIN: strain_protein, REFERENCE: reference_protein}
    site.models[STRAIN] = GeneModel(organism_abbrev="pfalDd2", cds=cds)
    site.contigs["pfalDd2", strain.sequence_id] = Contig.whole(
        "C" * left + gene + "C" * FLANK
    )
    return site
