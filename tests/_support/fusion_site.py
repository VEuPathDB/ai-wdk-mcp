import pytest
from tests._support.audit_site import AuditSite
from tests._support.proteins import PROTEIN, row

from veupathdb_mcp.audit import fusion_inputs
from veupathdb_mcp.audit.genes import GeneRow

MEMBER = "PfDd2_010001"
REFERENCE_GENE = "PF3D7_0100500"
DD2 = "Plasmodium falciparum Dd2"
PF3D7 = "Plasmodium falciparum 3D7"
PARTNER_GROUP = "OG7_0000777"
REFERENCE = PROTEIN[:120]
NEIGHBOUR = PROTEIN[120:]
UNRELATED = (
    "RVRRTWHGTSYGERLFDVCYPRYGYATDCCHIYARMRWHTILSADRKQVDKMITLADWEPELPDAAHHCSPPQDWHKMDL"
)
SIDE_PROTEIN = "ACDEFGHIKLMNPQRSTVWY" * 3
BESIDE_REFERENCE = [f"PF3D7_01000{n}0" for n in (2, 3, 4, 6, 7, 8)]
PARTNER_COPY = "PfDd2_010003"
MEMBER_PRODUCT = "methionine aminopeptidase"
PARTNER_PRODUCT = "tRNA ligase"


class FusionSite(AuditSite):
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(monkeypatch)
        self.genomes: dict[str, list[GeneRow]] = {}
        self.genomes_read: list[str] = []
        self.orthologs_read: list[str] = []
        monkeypatch.setattr(fusion_inputs, "orthologs_of", self.orthologs_of)
        monkeypatch.setattr(fusion_inputs, "genes_of_genome", self.genes_of_genome)
        monkeypatch.setattr(fusion_inputs, "proteins_of", self.proteins_of)

    async def orthologs_of(self, site_id: str, gene: str) -> list[GeneRow]:
        self.orthologs_read.append(gene)
        return await super().orthologs_of(site_id, gene)

    async def genes_of_genome(self, site_id: str, organism: str) -> list[GeneRow]:
        self.genomes_read.append(organism)
        return self.genomes[organism]


def placed(gene: str, organism: str, contig: str, start: int, group: str) -> GeneRow:
    return row(gene, organism, 20, start=start).model_copy(
        update={"sequence_id": contig, "ortholog_group": group}
    )


def _reference_genome(reference: GeneRow, partner_group: str) -> list[GeneRow]:
    left, right = BESIDE_REFERENCE[:3], BESIDE_REFERENCE[3:]
    genes = [
        placed("PF3D7_0100010", PF3D7, "Pf3D7_01", 1001, "OG7_0000010"),
        *(
            placed(g, PF3D7, "Pf3D7_01", 10000 * n + 1, f"OG7_00000{n}0")
            for n, g in enumerate(left, start=2)
        ),
        *(
            placed(g, PF3D7, "Pf3D7_01", 10000 * n + 1, f"OG7_00000{n}0")
            for n, g in enumerate(right, start=6)
        ),
        placed("PF3D7_0100900", PF3D7, "Pf3D7_01", 90001, "OG7_0000090"),
        placed("PF3D7_0200100", PF3D7, "Pf3D7_02", 50001, partner_group),
    ]
    genes[3] = genes[3].model_copy(
        update={"ortholog_group": partner_group, "product": PARTNER_PRODUCT}
    )
    return [*genes, reference]


def _member_genome(member: GeneRow) -> list[GeneRow]:
    return [
        member,
        placed("PfDd2_010002", DD2, "PfDd2_01", 40001, "OG7_0000020"),
        placed(PARTNER_COPY, DD2, "PfDd2_01", 60001, PARTNER_GROUP),
        *(
            placed(f"PfDd2_01000{n}", DD2, "PfDd2_01", 10000 * n + 50001, "OG7_0")
            for n in (4, 5, 6)
        ),
        placed("PfDd2_010009", DD2, "PfDd2_01", 900001, PARTNER_GROUP),
        placed("PfDd2_020001", DD2, "PfDd2_02", 50001, PARTNER_GROUP),
    ]


def fusion_site(
    monkeypatch: pytest.MonkeyPatch,
    member_protein: str,
    *,
    partner_group: str = PARTNER_GROUP,
    relatives: int = 8,
) -> FusionSite:
    site = FusionSite(monkeypatch)
    member = placed(MEMBER, DD2, "PfDd2_01", 50001, "OG7_0000001").model_copy(
        update={"protein_length": len(member_protein), "product": MEMBER_PRODUCT}
    )
    reference = placed(REFERENCE_GENE, PF3D7, "Pf3D7_01", 50001, "OG7_0000001")
    reference = reference.model_copy(update={"protein_length": len(REFERENCE)})
    group = [
        member,
        reference,
        *(row(f"P{i}", f"Plasmodium species{i} X", 120) for i in range(relatives)),
    ]
    site.rows = group
    site.orthologs[MEMBER] = group
    site.genomes = {
        PF3D7: _reference_genome(reference, partner_group),
        DD2: _member_genome(member),
    }
    site.proteins = {
        MEMBER: member_protein,
        REFERENCE_GENE: REFERENCE,
        BESIDE_REFERENCE[2]: NEIGHBOUR,
        BESIDE_REFERENCE[0]: SIDE_PROTEIN,
        BESIDE_REFERENCE[4]: SIDE_PROTEIN[::-1],
    }
    return site
