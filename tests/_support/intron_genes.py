from typing import Literal

from tests._support.proteins import PROTEIN, back_translate
from veupathdb.jbrowse import GenomeWindow

from veupathdb_mcp.audit.codes import reverse_complement
from veupathdb_mcp.audit.introns import GeneStructure, RnaJunction, Span

START = 1001
FLANK = "C" * 60
FILL = "GT" + "C" * 56 + "AG"
E1, I1, E2, I2 = (1061, 1150), (1151, 1210), (1211, 1300), (1301, 1360)
E3, I3, E4 = (1361, 1450), (1451, 1510), (1511, 1603)
SPLICED = PROTEIN[:120]
SEQUENCE = (
    FLANK
    + FILL.join(back_translate(PROTEIN[k : k + 30]) for k in range(0, 120, 30))
    + "TAA"
    + FLANK
)
END = START + len(SEQUENCE) - 1


def dna() -> GenomeWindow:
    return GenomeWindow(seqid="contig", start=START, sequence=SEQUENCE)


def structure(
    exons: list[Span], cds: list[Span] | None = None, start: int | None = None
) -> GeneStructure:
    return GeneStructure(
        transcript="PcyX_1-t1",
        other_transcripts=0,
        strand="+",
        start=start or min(a for a, _ in exons),
        end=max(b for _, b in exons),
        exons=exons,
        cds=cds or exons,
    )


def junction(
    span: Span,
    reads: int,
    *,
    strong: bool = True,
    strand: Literal["+", "-", ".", "?"] = "+",
    track: str = "first",
) -> RnaJunction:
    return RnaJunction(
        start=span[0],
        end=span[1],
        strand=strand,
        reads=reads,
        strong=strong,
        track=track,
    )


def _mirror(span: Span) -> Span:
    return START + END - span[1], START + END - span[0]


def flipped(
    exons: list[Span], junctions: list[RnaJunction]
) -> tuple[GeneStructure, GenomeWindow, list[RnaJunction]]:
    mirrored = sorted(_mirror(span) for span in exons)
    return (
        GeneStructure(
            transcript="PcyX_1-t1",
            other_transcripts=0,
            strand="-",
            start=mirrored[0][0],
            end=mirrored[-1][1],
            exons=mirrored,
            cds=mirrored,
        ),
        GenomeWindow(
            seqid="contig", start=START, sequence=reverse_complement(SEQUENCE)
        ),
        [
            junction(_mirror((j.start, j.end)), j.reads, strand="-", track=j.track)
            for j in junctions
        ],
    )
