"""Record the gene model reads the strain-model check adds to its recorded wires, from
a QA site, by single gene record reads.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_strain.py --models [--out DIR]``.
"""

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue
from scripts.record_audit_fixtures import (
    FIXTURES,
    LengthWire,
    act_as_the_test_account,
    served_body,
    write_lengths,
)
from veupathdb.devtools import use_qa_sites
from veupathdb.wdk import close_all_clients

from veupathdb_mcp.audit import (
    MODEL_TABLE,
    ORGANISM_ATTRIBUTE,
    gene_record,
)

SITE = "plasmodb"
MODEL_BUDGET = 2
INTRONS_PKAC = "introns_pcynM_pkac.json"


class StrainPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    reference: str


class StrainWire(LengthWire):
    reference: str
    annotation: list[str]


PAIRS = [
    StrainPair(file="strain_pcynM_pkac.json", reference="PCYB_074210"),
    StrainPair(file="strain_pfalDd2_yip1.json", reference="PF3D7_1472100"),
]


class _Served(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: list[dict[str, str]]
    tables: dict[str, list[JsonValue]] = {}

    @property
    def gene(self) -> str:
        return next(part["value"] for part in self.id if part["name"] == "source_id")


class _IntronModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model_record: _Served


def model_rows(records: list[JsonValue], gene: str) -> list[JsonValue] | None:
    served = [_Served.model_validate(body) for body in records]
    return next(
        (
            s.tables[MODEL_TABLE]
            for s in served
            if s.gene == gene and MODEL_TABLE in s.tables
        ),
        None,
    )


def agrees_with_introns(wire: StrainWire, introns: str) -> bool:
    held = _IntronModel.model_validate_json(introns).model_record
    return model_rows(wire.records, wire.gene) == held.tables.get(MODEL_TABLE)


async def record_models(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    introns = (into / INTRONS_PKAC).read_text()
    wires = {
        pair.file: StrainWire.model_validate_json((into / pair.file).read_text())
        for pair in PAIRS
    }
    pkac = wires[PAIRS[0].file]
    if not agrees_with_introns(pkac, introns):
        msg = f"the strain model of {pkac.gene} differs from {INTRONS_PKAC}"
        raise ValueError(msg)
    sent = 0
    try:
        for name, wire in wires.items():
            if model_rows(wire.records, wire.reference) is not None:
                continue
            if sent == MODEL_BUDGET:
                msg = f"the recording spent its {MODEL_BUDGET} model reads"
                raise RuntimeError(msg)
            sent += 1
            read = await gene_record(
                SITE, wire.reference, [ORGANISM_ATTRIBUTE], [MODEL_TABLE]
            )
            print("model", wire.reference, "200")
            wires[name] = wire.model_copy(
                update={"records": [*wire.records, served_body(read)]}
            )
    finally:
        await close_all_clients()
        print("model reads sent", sent)
    write_lengths(into, wires)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    parser.add_argument("--models", action="store_true", required=True)
    arguments = parser.parse_args()
    asyncio.run(record_models(arguments.out))
