"""Whether a selenoprotein model ends at the TGA that encodes its selenocysteine."""

from __future__ import annotations

import difflib
from typing import Literal, Self

from pydantic import ConfigDict, model_validator
from veupathdb.model import CamelModel

from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement, six_frames

type SecVerdict = Literal[
    "CONTAINS_SEC", "STOPS_AT_SEC", "NOT_AT_SEC", "MODEL_NOT_FOUND"
]

TAIL_IDENTITY = 0.8
END_SLACK = 3
_ANCHOR = 6
_LOOKAHEAD = 12
_SEC_CODON = "TGA"


class SecCheck(CamelModel):
    model_config = ConfigDict(frozen=True)

    verdict: SecVerdict
    after_model_end: str
    reference_tail: str
    tail_identity: float | None
    sec_aligned: bool | None

    @model_validator(mode="after")
    def _stops_where_the_reference_has_sec(self) -> Self:
        contains = self.verdict == "CONTAINS_SEC"
        if contains != (self.sec_aligned is None):
            msg = "a check aligns the model end to the reference unless it holds Sec"
            raise ValueError(msg)
        compared = self.verdict in {"STOPS_AT_SEC", "NOT_AT_SEC"}
        if compared != (self.tail_identity is not None):
            msg = "a check compares the tail only where it found the model end"
            raise ValueError(msg)
        matched = self.tail_identity is not None and self.tail_identity >= TAIL_IDENTITY
        if self.verdict == "STOPS_AT_SEC" and not (self.sec_aligned and matched):
            msg = (
                "a model stops at Sec only when its end aligns before the reference "
                f"Sec and the tail is at least {TAIL_IDENTITY} identical"
            )
            raise ValueError(msg)
        return self


def sec_tail(protein: str) -> str:
    return protein[protein.index("U") :] if "U" in protein else ""


def sec_aligned(model_protein: str, reference_protein: str) -> bool:
    last = len(model_protein) - 1
    before_sec = len(reference_protein) - len(sec_tail(reference_protein)) - 1
    blocks = [
        (a, b, size)
        for a, b, size in difflib.SequenceMatcher(
            None, model_protein, reference_protein, autojunk=False
        ).get_matching_blocks()
        if size and a <= last
    ]
    if not blocks:
        return False
    a, b, size = blocks[-1]
    return last - (a + size - 1) <= END_SLACK and b + last - a == before_sec


def tail_identity(expected: str, genome: str) -> float:
    if not expected:
        return 1.0
    same = 0
    for want, read in zip(expected, genome, strict=False):
        if read == "*" and want != "*":
            break
        same += want == read
    return same / len(expected)


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
        return SecCheck(
            verdict="CONTAINS_SEC",
            after_model_end="",
            reference_tail=tail,
            tail_identity=None,
            sec_aligned=None,
        )
    aligned = sec_aligned(model_protein, reference_protein)
    not_found = SecCheck(
        verdict="MODEL_NOT_FOUND",
        after_model_end="",
        reference_tail=tail,
        tail_identity=None,
        sec_aligned=aligned,
    )
    if len(model_protein) < _ANCHOR:
        return not_found
    anchor = model_protein[-_ANCHOR:]
    expected = tail[1:].split("*", 1)[0].replace("U", "*")
    coding = {"+": dna, "-": reverse_complement(dna)}
    seen: list[tuple[str, float]] = []
    for frame in six_frames(dna, code):
        if frame.strand != strand:
            continue
        at = frame.protein.find(anchor)
        while at >= 0:
            end = at + _ANCHOR
            after = frame.protein[end : end + _LOOKAHEAD]
            codon = coding[strand][frame.offset + 3 * end : frame.offset + 3 * end + 3]
            identity = tail_identity(expected, frame.protein[end + 1 :])
            seen.append((after, identity))
            if aligned and codon == _SEC_CODON and identity >= TAIL_IDENTITY:
                return SecCheck(
                    verdict="STOPS_AT_SEC",
                    after_model_end=after,
                    reference_tail=tail,
                    tail_identity=identity,
                    sec_aligned=aligned,
                )
            at = frame.protein.find(anchor, at + 1)
    if not seen:
        return not_found
    after, identity = seen[-1]
    return SecCheck(
        verdict="NOT_AT_SEC",
        after_model_end=after,
        reference_tail=tail,
        tail_identity=identity,
        sec_aligned=aligned,
    )
