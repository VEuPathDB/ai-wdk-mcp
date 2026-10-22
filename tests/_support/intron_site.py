import pytest
from pydantic import JsonValue
from tests._support.intron_genes import E1, E3, E4, I1, I2, I3, dna
from tests._support.proteins import PROTEIN
from veupathdb.errors import WDKError
from veupathdb.jbrowse import (
    GenomeWindow,
    SequenceNotIndexedError,
    TrackConfig,
    TrackList,
)
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit import (
    gene_ids,
    gene_models,
    introns_inputs,
    record_reads,
    track_reads,
)
from veupathdb_mcp.audit.genes import GeneRow, OrthologGroup, OrthologRow

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


def ortholog_row(
    gene: str, organism: str, length: int | None, reference: str = "no"
) -> OrthologRow:
    return OrthologRow.model_validate(
        {
            "ortho_gene_source_id": gene,
            "organism": organism,
            "is_syntenic": "yes",
            "protein_length": "" if length is None else str(length),
            "gene_product": "kinase",
            "is_reference_strain": reference,
            "has_comment": "no",
        }
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
        self.window_served = window
        self.window_refusal: Exception | None = None
        self.abbrevs: list[str] = []
        self.track_reads: list[Region] = []
        self.windows: list[Region] = []
        self.lists: list[tuple[str, str]] = []
        monkeypatch.setattr(introns_inputs, "get_jbrowse_client", lambda site: self)
        monkeypatch.setattr(track_reads, "TabixReader", self.reader)
        monkeypatch.setattr(track_reads, "GenomeReader", self.reader)

    def reader(self, client: "JBrowse") -> "JBrowse":
        return client

    async def junction_tracks(self, abbrev: str) -> list[TrackConfig]:
        self.abbrevs.append(abbrev)
        listed = TrackList.model_validate(self._tracks)
        return [track for track in listed.tracks if track.reads_with_tabix]

    async def track_list(self, kind: str, abbrev: str) -> TrackList:
        self.lists.append((kind, abbrev))
        return TrackList(tracks=[])

    async def coverage_tracks(self, abbrev: str) -> list[TrackConfig]:
        self.lists.append(("rnaseq", abbrev))
        return []

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
        if self.window_refusal is not None:
            raise self.window_refusal
        return self.window_served


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
        self.proteins_read: list[str] = []
        self.tables_read: list[str] = []
        monkeypatch.setattr(record_reads, "_row", self.record_row)
        monkeypatch.setattr(record_reads, "_protein", self.record_protein)
        monkeypatch.setattr(gene_ids, "genes_by_text", self.genes_by_text)
        monkeypatch.setattr(gene_models, "gene_record", self.gene_record)
        monkeypatch.setattr(introns_inputs, "orthologs_of", self.orthologs_of)

    async def record_row(self, site_id: str, gene: str) -> GeneRow:
        if gene != self.row.gene:
            msg = f"{gene} has no record"
            raise WDKError(msg, status=404)
        return self.row

    async def record_protein(self, site_id: str, gene: str) -> str | None:
        self.proteins_read.append(gene)
        return self.proteins.get(gene)

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

    async def orthologs_of(self, site_id: str, gene: str) -> OrthologGroup:
        self.tables_read.append(gene)
        if self.table_refusal is not None:
            raise self.table_refusal
        table = [
            ortholog_row(GENE, "Plasmodium cynomolgi strain X", 90),
            ortholog_row("PCYB_1", "Plasmodium cynomolgi strain B", 120),
            ortholog_row("PVX_1", "Plasmodium vivax Sal-1", 150),
            ortholog_row("PKNH_1", "Plasmodium knowlesi strain H", 130),
            ortholog_row("PVX_9", "Plasmodium vivax Sal-1", None),
            ortholog_row("PVX_1", "Plasmodium vivax Sal-1", 150),
        ]
        named: dict[str, OrthologRow] = {}
        for row in table:
            if row.gene != gene:
                named.setdefault(row.gene, row)
        return OrthologGroup(gene=gene, members=list(named.values()))
