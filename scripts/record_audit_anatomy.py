"""Record the gene records and genome windows the pseudogene anatomy tests read
from a QA site.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_anatomy.py [--out DIR]``.
"""

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue
from scripts.record_audit_fixtures import (
    FIXTURES,
    LOCATION,
    GeneLocation,
    act_as_the_test_account,
)
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import (
    GenomeReader,
    GenomeWindow,
    close_all_jbrowse_clients,
    get_jbrowse_client,
)
from veupathdb.wdk import close_all_clients

from veupathdb_mcp.audit.gene_models import (
    MODEL_TABLE,
    ORGANISM_ATTRIBUTE,
    GeneModel,
    gene_record,
)
from veupathdb_mcp.audit.served import PSEUDOGENE_PAD

SITE = "plasmodb"
RECORD_ATTRIBUTES = [*LOCATION, ORGANISM_ATTRIBUTE, "organism_full"]


class AnatomyTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    strain_gene: str
    reference_gene: str


class AnatomyRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    strain_gene: str
    reference_gene: str
    records: dict[str, JsonValue]
    windows: list[GenomeWindow]
    contig_length: int


TARGETS = [
    AnatomyTarget(
        file="anatomy_pfalNF54_piga.json",
        strain_gene="PfNF54_100037200:pseudogene",
        reference_gene="PF3D7_1032400",
    ),
    AnatomyTarget(
        file="anatomy_pfalNF54_pagm.json",
        strain_gene="PfNF54_110034300:pseudogene",
        reference_gene="PF3D7_1130000",
    ),
]


def spans(reference: GeneLocation, strain: GeneLocation) -> list[tuple[int, int]]:
    return [
        (reference.start_min, reference.end_max),
        (strain.start_min - PSEUDOGENE_PAD, strain.end_max + PSEUDOGENE_PAD),
    ]


async def _recording(reader: GenomeReader, target: AnatomyTarget) -> AnatomyRecording:
    genes = [target.reference_gene, target.strain_gene]
    records = {
        gene: await gene_record(SITE, gene, RECORD_ATTRIBUTES, [MODEL_TABLE])
        for gene in genes
    }
    places = [GeneLocation.model_validate(records[gene].attributes) for gene in genes]
    abbrevs = [GeneModel.from_record(records[gene]).organism_abbrev for gene in genes]
    windows = [
        await reader.window(abbrev, place.sequence_id, start, end)
        for abbrev, place, (start, end) in zip(
            abbrevs, places, spans(*places), strict=True
        )
    ]
    return AnatomyRecording(
        site=SITE,
        strain_gene=target.strain_gene,
        reference_gene=target.reference_gene,
        records={
            gene: record.model_dump(mode="json", by_alias=True)
            for gene, record in records.items()
        },
        windows=windows,
        contig_length=await reader.sequence_length(abbrevs[1], places[1].sequence_id),
    )


def write_recordings(into: Path, recordings: dict[str, AnatomyRecording]) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name, recorded in recordings.items():
        (into / name).write_text(recorded.model_dump_json(indent=1) + "\n")


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    reader = GenomeReader(get_jbrowse_client(SITE))
    try:
        recordings = {t.file: await _recording(reader, t) for t in TARGETS}
    finally:
        await close_all_jbrowse_clients()
        await close_all_clients()
    write_recordings(into, recordings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.out))
