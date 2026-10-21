import pytest
from tests._support.audit_site import reads_for
from tests._support.proteins import back_translate
from veupathdb.jbrowse import GenomeWindow

from veupathdb_mcp.audit import missing_inputs, served
from veupathdb_mcp.audit.gene_ids import GeneReads
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow

ARI = "Toxoplasma gondii ARI"
GT1 = "Toxoplasma gondii GT1"
EXAMPLE = "TGARI_257090"


def gene(
    name: str,
    start: int,
    *,
    organism: str = ARI,
    sequence_id: str = "KQ976331",
    group: str = "OG8_0000001",
) -> GeneRow:
    return GeneRow(
        gene=name,
        organism=organism,
        ortholog_group=group,
        protein_length=300,
        name="",
        product="conserved protein",
        sequence_id=sequence_id,
        start=start,
        end=start + 899,
        strand="+",
        pseudo=False,
        gene_type="protein coding gene",
    )


def tga_for_w(protein: str) -> str:
    return "".join("TGA" if a == "W" else back_translate(a) for a in protein)


class MissingSite:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.rows: list[GeneRow] = []
        self.proteins: dict[str, str] = {}
        self.models: dict[str, GeneModel] = {}
        self.contigs: dict[str, tuple[int, str]] = {}
        self.rows_read: list[list[str]] = []
        self.genomes_read: list[str] = []
        self.models_read: list[str] = []
        self.organisms_read: list[str] = []
        self.windows: list[tuple[str, str, int, int]] = []
        monkeypatch.setattr(served, "rows_named", self.rows_named)
        monkeypatch.setattr(served, "genes_by_text", self.genes_by_text)
        monkeypatch.setattr(served, "proteins_of", self.proteins_of)
        monkeypatch.setattr(missing_inputs, "genes_of_genome", self.genes_of_genome)
        monkeypatch.setattr(missing_inputs, "gene_model", self.gene_model)
        monkeypatch.setattr(missing_inputs, "gene_organism", self.gene_organism)
        monkeypatch.setattr(missing_inputs, "get_jbrowse_client", lambda site_id: self)
        monkeypatch.setattr(missing_inputs, "GenomeReader", lambda client: client)

    async def gene_rows(self, site_id: str, gene_ids: list[str]) -> list[GeneRow]:
        self.rows_read.append(gene_ids)
        return [row for row in self.rows if row.gene in gene_ids]

    async def rows_named(self, site_id: str, gene_ids: list[str]) -> GeneReads:
        return reads_for(await self.gene_rows(site_id, gene_ids), gene_ids, {}, {})

    async def genes_by_text(self, site_id: str, gene_id: str) -> list[GeneRow]:
        return []

    async def proteins_of(self, site_id: str, gene_ids: list[str]) -> dict[str, str]:
        return {g: self.proteins[g] for g in gene_ids if g in self.proteins}

    async def genes_of_genome(self, site_id: str, organism: str) -> list[GeneRow]:
        self.genomes_read.append(organism)
        return [row for row in self.rows if row.organism == organism]

    async def gene_model(self, site_id: str, gene: str) -> GeneModel:
        self.models_read.append(gene)
        return self.models[gene]

    async def gene_organism(self, site_id: str, gene: str) -> str:
        self.organisms_read.append(gene)
        return self.models[gene].organism_abbrev

    async def window(
        self, abbrev: str, seqid: str, start: int, end: int
    ) -> GenomeWindow:
        self.windows.append((abbrev, seqid, start, end))
        first, sequence = self.contigs[seqid]
        low, high = max(start, first), min(end, first + len(sequence) - 1)
        return GenomeWindow(
            seqid=seqid, start=low, sequence=sequence[low - first : high - first + 1]
        )
