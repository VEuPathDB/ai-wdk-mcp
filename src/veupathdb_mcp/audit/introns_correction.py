"""The model an explained unread intron implies: its junctions cut out, or the intron
read as exon, translated from the annotated start."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from veupathdb.errors import DataParsingError
from veupathdb.jbrowse import GenomeWindow
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement, translate
from veupathdb_mcp.audit.introns import GeneStructure, Span, Strand, UnreadIntron


class IntronCorrection(CamelModel):
    model_config = ConfigDict(frozen=True)

    cds: list[Span]
    protein: str
    frame_kept: bool


class _Orf(BaseModel):
    model_config = ConfigDict(frozen=True)

    protein: str
    stop: bool
    positions: list[int]


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(spans: list[Span], cuts: list[Span]) -> list[Span]:
    kept = _merge(spans)
    for cut_start, cut_end in cuts:
        kept = [
            piece
            for start, end in kept
            for piece in (
                (start, min(end, cut_start - 1)),
                (max(start, cut_end + 1), end),
            )
            if piece[0] <= piece[1]
        ]
    return kept


def _complement(bases: str) -> str:
    return reverse_complement(bases)[::-1]


def _orf(
    dna: GenomeWindow, exons: list[Span], strand: Strand, edge: int, code: GeneticCode
) -> _Orf:
    exonic = [p for start, end in _merge(exons) for p in range(start, end + 1)]
    if strand == "+":
        path = [p for p in exonic if p >= edge] + list(
            range(exonic[-1] + 1, dna.end + 1)
        )
    else:
        path = [p for p in reversed(exonic) if p <= edge] + list(
            range(exonic[0] - 1, dna.start - 1, -1)
        )
    bases = "".join(dna.sequence[p - dna.start] for p in path)
    residues = translate(bases if strand == "+" else _complement(bases), code)
    protein, stop, _ = residues.partition("*")
    used = 3 * (len(protein) + 1) if stop else 3 * len(protein)
    return _Orf(protein=protein, stop=bool(stop), positions=path[:used])


def correct_model(
    model: GeneStructure,
    unread: list[UnreadIntron],
    dna: GenomeWindow,
    code: GeneticCode,
) -> IntronCorrection:
    if not unread or any(u.outcome == "UNEXPLAINED" for u in unread):
        msg = "a model is corrected only when no unread intron is UNEXPLAINED"
        raise ValueError(msg)
    parts = [*model.exons, *model.cds]
    if not dna.start <= min(a for a, _ in parts) <= max(b for _, b in parts) <= dna.end:
        msg = (
            f"{model.transcript} lies outside the window "
            f"{dna.seqid}:{dna.start}-{dna.end}"
        )
        raise DataParsingError(msg)
    exons = _subtract(
        [*model.exons, *(u.span for u in unread)],
        [(r.start, r.end) for u in unread for r in u.replacement],
    )
    annotated = _orf(dna, model.exons, model.strand, model.start_edge, code)
    corrected = _orf(dna, exons, model.strand, model.start_edge, code)
    return IntronCorrection(
        cds=_merge([(p, p) for p in corrected.positions]),
        protein=corrected.protein,
        frame_kept=annotated.stop
        and corrected.stop
        and annotated.positions[-3:] == corrected.positions[-3:],
    )
