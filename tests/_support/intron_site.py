import pytest
from pydantic import JsonValue
from tests._support.audit_site import reads_for
from tests._support.intron_genes import E1, E3, E4, I1, I2, I3, dna
from tests._support.proteins import PROTEIN
from veupathdb.jbrowse import (
    GenomeWindow,
    SequenceNotIndexedError,
    TrackConfig,
    TrackList,
)
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import gene_models, introns_inputs, served
from veupathdb_mcp.audit.gene_ids import GeneReads
from veupathdb_mcp.audit.genes import GeneRow, OrthologRow

type Region = tuple[str, str, int, int]
type Span = tuple[int, int]

TABIX = "JBrowse/Store/SeqFeature/GFF3Tabix"
GENE = "PcyX_1"
TRACK = "PcynomolgiX/genomeBrowser/gff/unifiedIntronJunction.gff.gz"
OTHER_TRACK = "PcynomolgiX/genomeBrowser/gff/otherJunction.gff.gz"
ANNOTATED = PROTEIN[:30] + PROTEIN[60:120]
READS: dict[Span, int] = {I1: 100, I2: 120, I3: 300}


def track_list(*paths: str) -> JsonValue:
    return {
        "tracks": [
            {
                "storeClass": TABIX,
                "urlTemplate": f"/a/service/jbrowse/store?data={path}",
                "key": "RNA-Seq Evidence for Introns",
            }
            for path in paths
        ]
    }


def gff_line(
    seqid: str,
    span: Span,
    reads: int,
    *,
    strand: str = "+",
    evidence: str = "Strong Evidence",
) -> str:
    start, end = span
    return (
        f"{seqid}\tVEuPathDB\tintronJunction\t{start}\t{end}\t{reads}\t{strand}\t.\t"
        f"contained=1;isrpm=1.00;totalscore={reads};intronpercent=;"
        f"annotatedintron=No;evidence={evidence};ID={seqid}_{start}_{end}_0"
    )


def model_rows(
    exons: list[Span], kinds: tuple[str, ...], transcript: str = f"{GENE}-t1"
) -> list[JsonValue]:
    return [
        {
            "type": kind,
            "transcript_ids": transcript,
            "gm_start": str(start),
            "gm_end": str(end),
            "strand": "+",
            "sequence_id": "contig",
            "source_id": GENE,
        }
        for start, end in exons
        for kind in kinds
    ]


def ortholog_row(gene: str, organism: str) -> OrthologRow:
    return OrthologRow.model_validate(
        {"ortho_gene_source_id": gene, "organism": organism, "is_syntenic": "yes"}
    )


class JBrowse:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tracks: JsonValue,
        lines: dict[tuple[str, str], list[str]],
        window: GenomeWindow,
    ) -> None:
        self._tracks = tracks
        self._lines = lines
        self._window = window
        self.abbrevs: list[str] = []
        self.track_reads: list[Region] = []
        self.windows: list[Region] = []
        monkeypatch.setattr(introns_inputs, "get_jbrowse_client", lambda site: self)
        monkeypatch.setattr(introns_inputs, "TabixReader", self.reader)
        monkeypatch.setattr(introns_inputs, "GenomeReader", self.reader)

    def reader(self, client: "JBrowse") -> "JBrowse":
        return client

    async def junction_tracks(self, abbrev: str) -> list[TrackConfig]:
        self.abbrevs.append(abbrev)
        listed = TrackList.model_validate(self._tracks)
        return [track for track in listed.tracks if track.reads_with_tabix]

    async def lines(
        self, track: TrackConfig, seqid: str, start: int, end: int
    ) -> list[str]:
        self.track_reads.append((track.data_path, seqid, start, end))
        if (track.data_path, seqid) not in self._lines:
            raise SequenceNotIndexedError(track.data_path, seqid)
        return self._lines[track.data_path, seqid]

    async def window(
        self, abbrev: str, seqid: str, start: int, end: int
    ) -> GenomeWindow:
        self.windows.append((abbrev, seqid, start, end))
        return self._window


def junctions(
    monkeypatch: pytest.MonkeyPatch,
    reads: dict[Span, int],
    paths: tuple[str, ...] = (TRACK,),
    indexed: tuple[str, ...] = (TRACK,),
) -> JBrowse:
    lines = [gff_line("contig", span, n) for span, n in reads.items()]
    return JBrowse(
        monkeypatch,
        track_list(*paths),
        {(path, "contig"): lines for path in indexed},
        dna(),
    )


class Site:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, end: int = E4[1]) -> None:
        self.row = GeneRow(
            gene=GENE,
            organism="Plasmodium cynomolgi strain X",
            ortholog_group="OG8_0000081",
            protein_length=len(ANNOTATED),
            name="PKAc",
            product="cAMP-dependent protein kinase catalytic subunit",
            sequence_id="contig",
            start=E1[0],
            end=end,
            strand="+",
            pseudo=False,
            gene_type="protein coding gene",
        )
        self.model: list[JsonValue] = model_rows([E1, E3, E4], ("CDS", "Exon"))
        self.proteins = {
            GENE: ANNOTATED,
            "PVX_1": PROTEIN[:150],
            "PKNH_1": PROTEIN[:130],
            "PCYB_1": PROTEIN[:120],
        }
        self.table_refusal: Exception | None = None
        self.records_read: list[list[str]] = []
        self.proteins_read: list[list[str]] = []
        self.tables_read: list[str] = []
        monkeypatch.setattr(served, "rows_named", self.rows_named)
        monkeypatch.setattr(served, "genes_by_text", self.genes_by_text)
        monkeypatch.setattr(gene_models, "gene_record", self.gene_record)
        monkeypatch.setattr(introns_inputs, "proteins_of", self.proteins_of)
        monkeypatch.setattr(served, "proteins_of", self.proteins_of)
        monkeypatch.setattr(introns_inputs, "ortholog_table", self.ortholog_table)

    async def gene_rows(self, site_id: str, gene_ids: list[str]) -> list[GeneRow]:
        return [self.row] if self.row.gene in gene_ids else []

    async def rows_named(self, site_id: str, gene_ids: list[str]) -> GeneReads:
        return reads_for(await self.gene_rows(site_id, gene_ids), gene_ids, {}, {})

    async def genes_by_text(self, site_id: str, gene_id: str) -> list[GeneRow]:
        return []

    async def gene_record(
        self, site_id: str, gene: str, attributes: list[str], tables: list[str]
    ) -> WDKRecordInstance:
        self.records_read.append(tables)
        return WDKRecordInstance.model_validate(
            {
                "attributes": {"organismAbbrev": "pcynX"},
                "tables": {"GeneModelDump": self.model},
            }
        )

    async def proteins_of(self, site_id: str, gene_ids: list[str]) -> dict[str, str]:
        self.proteins_read.append(gene_ids)
        return {g: self.proteins[g] for g in gene_ids if g in self.proteins}

    async def ortholog_table(self, site_id: str, gene: str) -> list[OrthologRow]:
        self.tables_read.append(gene)
        if self.table_refusal is not None:
            raise self.table_refusal
        return [
            ortholog_row(GENE, "Plasmodium cynomolgi strain X"),
            ortholog_row("PCYB_1", "Plasmodium cynomolgi strain B"),
            ortholog_row("PVX_1", "Plasmodium vivax Sal-1"),
            ortholog_row("PKNH_1", "Plasmodium knowlesi strain H"),
            ortholog_row("PVX_9", "Plasmodium vivax Sal-1"),
            ortholog_row("PVX_1", "Plasmodium vivax Sal-1"),
        ]
