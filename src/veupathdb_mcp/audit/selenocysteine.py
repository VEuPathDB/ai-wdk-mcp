"""Whether a selenoprotein model ends at the TGA that encodes its selenocysteine."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement, six_frames

type SecVerdict = Literal[
    "CONTAINS_SEC", "STOPS_AT_SEC", "NOT_AT_SEC", "MODEL_NOT_FOUND"
]

_ANCHOR = 6
_LOOKAHEAD = 12
_SEC_CODON = "TGA"


class SecCheck(CamelModel):
    model_config = ConfigDict(frozen=True)

    verdict: SecVerdict
    after_model_end: str
    reference_tail: str


def sec_tail(protein: str) -> str:
    return protein[protein.index("U") :] if "U" in protein else ""


def check_sec_stop(
    model_protein: str,
    reference_protein: str,
    dna: str,
    strand: Literal["+", "-"],
    code: GeneticCode,
) -> SecCheck:
    tail = sec_tail(reference_protein)
    if not tail:
        msg = "the reference protein holds no selenocysteine"
        raise ValueError(msg)
    if "U" in model_protein:
        return SecCheck(verdict="CONTAINS_SEC", after_model_end="", reference_tail=tail)
    if len(model_protein) < _ANCHOR:
        return SecCheck(
            verdict="MODEL_NOT_FOUND", after_model_end="", reference_tail=tail
        )
    anchor = model_protein[-_ANCHOR:]
    expected = tail[1:].split("*", 1)[0].replace("U", "*")
    coding = {"+": dna, "-": reverse_complement(dna)}
    seen: list[str] = []
    for frame in six_frames(dna, code):
        if frame.strand != strand:
            continue
        at = frame.protein.find(anchor)
        while at >= 0:
            end = at + _ANCHOR
            after = frame.protein[end : end + _LOOKAHEAD]
            codon = coding[strand][frame.offset + 3 * end : frame.offset + 3 * end + 3]
            beyond = frame.protein[end + 1 : end + 1 + len(expected)]
            seen.append(after)
            if codon == _SEC_CODON and beyond == expected:
                return SecCheck(
                    verdict="STOPS_AT_SEC", after_model_end=after, reference_tail=tail
                )
            at = frame.protein.find(anchor, at + 1)
    if not seen:
        return SecCheck(
            verdict="MODEL_NOT_FOUND", after_model_end="", reference_tail=tail
        )
    return SecCheck(verdict="NOT_AT_SEC", after_model_end=seen[-1], reference_tail=tail)
