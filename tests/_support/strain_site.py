from collections.abc import Callable

import pytest
from tests._support.audit_site import AuditSite, Contig
from tests._support.intron_site import track_list
from tests._support.proteins import back_translate, row
from veupathdb.jbrowse import SequenceNotIndexedError, TrackConfig, TrackList

from veupathdb_mcp.audit import ANNOTATION_TRACK, strain_inputs, track_reads
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow, OrthologGroup
from veupathdb_mcp.audit.pseudogene import CdsPart

STRAIN = "PfDd2_1"
REFERENCE = "PF3D7_1"
DD2 = "Plasmodium falciparum Dd2"
PF3D7 = "Plasmodium falciparum 3D7"
FLANK = 40000
INSERT = "ACDEFGHIKLMNPQRSTVWY" * 2


def annotation_line(gene: GeneRow) -> str:
    kind = "pseudogene" if gene.pseudo else "protein_coding_gene"
    return (
        f"{gene.sequence_id}\tVEuPathDB\t{kind}\t{gene.start}\t{gene.end}\t.\t"
        f"{gene.strand}\t.\tID={gene.gene};ebi_biotype=protein_coding"
    )


def _overlaps(line: str, seqid: str, start: int, end: int) -> bool:
    columns = line.split("\t")
    return columns[0] == seqid and int(columns[3]) <= end and int(columns[4]) >= start


class Annotation:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, served: Callable[[], list[str]]
    ) -> None:
        self._served = served
        self.refusal: Exception | None = None
        self.listed = True
        self.indexed = True
        self.groups = 1
        self.lists: list[str] = []
        self.reads: list[tuple[str, int, int]] = []
        monkeypatch.setattr(strain_inputs, "get_jbrowse_client", lambda site: self)
        monkeypatch.setattr(track_reads, "TabixReader", self.reader)

    def reader(self, client: "Annotation") -> "Annotation":
        return client

    async def track_list(self, kind: str, abbrev: str) -> TrackList:
        self.lists.append(abbrev)
        if self.refusal is not None:
            raise self.refusal
        paths = [f"Pspecies/{ANNOTATION_TRACK}"] if self.listed else []
        return TrackList.model_validate(track_list(*paths))

    async def chunk_group_count(
        self, track: TrackConfig, seqid: str, start: int, end: int
    ) -> int:
        if not self.indexed:
            raise SequenceNotIndexedError(track.data_path, seqid)
        return self.groups

    async def lines(
        self, track: TrackConfig, seqid: str, start: int, end: int
    ) -> list[str]:
        self.reads.append((seqid, start, end))
        return [line for line in self._served() if _overlaps(line, seqid, start, end)]


def install_annotation(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> Annotation:
    return Annotation(monkeypatch, lambda: lines)


class StrainSite(AuditSite):
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(monkeypatch)
        self.orthologs_read: list[str] = []
        self.annotation = Annotation(monkeypatch, self.annotated)
        monkeypatch.setattr(strain_inputs, "orthologs_of", self.orthologs_of)
        monkeypatch.setattr(strain_inputs, "gene_organism", self.gene_organism)

    def annotated(self) -> list[str]:
        listed = [*self.rows, *(r for rows in self.orthologs.values() for r in rows)]
        return [annotation_line(gene) for gene in {r.gene: r for r in listed}.values()]

    async def orthologs_of(self, site_id: str, gene: str) -> OrthologGroup:
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
