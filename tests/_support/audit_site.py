import re

import pytest
from pydantic import BaseModel, ConfigDict
from veupathdb.jbrowse import GenomeWindow

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow

type Window = tuple[str, str, int, int]


class Contig(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: int
    sequence: str
    length: int

    @classmethod
    def whole(cls, sequence: str) -> "Contig":
        return cls(start=1, sequence=sequence, length=len(sequence))

    def window(self, seqid: str, start: int, end: int) -> GenomeWindow:
        first, last = max(1, start), min(self.length, end)
        if first < self.start or last >= self.start + len(self.sequence):
            msg = f"{seqid}:{first}-{last} lies outside the recorded bases"
            raise ValueError(msg)
        return GenomeWindow(
            seqid=seqid,
            start=first,
            sequence=self.sequence[first - self.start : last - self.start + 1],
        )


class Genome:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.regions: dict[Window, str] = {}
        self.contigs: dict[tuple[str, str], Contig] = {}
        self.windows: list[Window] = []
        self.lengths_read: list[tuple[str, str]] = []
        self.refusal: Exception | None = None
        monkeypatch.setattr(served, "get_jbrowse_client", lambda site_id: self)
        monkeypatch.setattr(served, "GenomeReader", self.reader)

    def reader(self, client: "Genome") -> "Genome":
        return client

    async def window(self, abbrev: str, seqid: str, start: int, end: int):
        self.windows.append((abbrev, seqid, start, end))
        if self.refusal is not None:
            raise self.refusal
        if (abbrev, seqid) in self.contigs:
            return self.contigs[abbrev, seqid].window(seqid, start, end)
        sequence = self.regions.get(
            (abbrev, seqid, start, end), "N" * (end - start + 1)
        )
        return GenomeWindow(seqid=seqid, start=start, sequence=sequence)

    async def sequence_length(self, abbrev: str, seqid: str) -> int:
        self.lengths_read.append((abbrev, seqid))
        return self.contigs[abbrev, seqid].length


class AuditSite(Genome):
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(monkeypatch)
        self.rows: list[GeneRow] = []
        self.models: dict[str, GeneModel] = {}
        self.proteins: dict[str, str] = {}
        self.orthologs: dict[str, list[GeneRow]] = {}
        self.models_read: list[str] = []
        self.proteins_read: list[list[str]] = []
        monkeypatch.setattr(served, "gene_rows", self.gene_rows)
        monkeypatch.setattr(served, "orthologs_of", self.orthologs_of)
        monkeypatch.setattr(served, "gene_model", self.gene_model)
        monkeypatch.setattr(served, "proteins_of", self.proteins_of)

    async def gene_rows(self, site_id: str, gene_ids: list[str]) -> list[GeneRow]:
        return [row for row in self.rows if row.gene in gene_ids]

    async def orthologs_of(self, site_id: str, gene: str) -> list[GeneRow]:
        return self.orthologs[gene]

    async def gene_model(self, site_id: str, gene: str) -> GeneModel:
        self.models_read.append(gene)
        return self.models[gene]

    async def proteins_of(self, site_id: str, gene_ids: list[str]) -> dict[str, str]:
        self.proteins_read.append(gene_ids)
        return {gene: self.proteins[gene] for gene in gene_ids if gene in self.proteins}


def window_refused(gene: str, length: int) -> str:
    return re.escape(
        f"the {gene} window spans {length} bases; an audit reads at most "
        f"{served.AUDIT_MAX_WINDOW_BASES} bases of genome per window"
    )
