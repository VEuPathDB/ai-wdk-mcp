"""Record the mitochondrial contigs and the cytochrome b gene the organelle check
tests read from QA plasmodb.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_organelle.py [--out DIR]``.
"""

import argparse
import asyncio
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue
from scripts.record_audit_fixtures import FIXTURES
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import (
    GenomeReader,
    close_all_jbrowse_clients,
    get_jbrowse_client,
)
from veupathdb.testing.wdk_credentials import act_as_the_test_account
from veupathdb.wdk import close_all_clients

from veupathdb_mcp.audit.gene_ids import LOCATED_ATTRIBUTES
from veupathdb_mcp.audit.gene_models import (
    MODEL_TABLE,
    ORGANISM_ATTRIBUTE,
    GeneModel,
    gene_record,
)
from veupathdb_mcp.audit.genes import (
    GENOME_SEARCH,
    GeneRow,
    genome_answer,
    locus_tag_answers,
)
from veupathdb_mcp.audit.organelle_inputs import first_coding_gene

SITE = "plasmodb"
REFERENCE = "PF3D7_MIT02300"
GENE_FILE = "organelle_pfal3D7_cytb.json"
PROTEIN_ATTRIBUTE = "protein_sequence"


class ContigTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    organism: str
    seqid: str


class ContigRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    organism: str
    abbrev: str
    seqid: str
    length: int
    sequence: str
    served_meta: JsonValue
    genes: list[JsonValue]
    trim: str
    record: JsonValue


class GeneRecording(BaseModel):
    model_config = ConfigDict(frozen=True)

    gene: str
    report: JsonValue
    record: JsonValue


CONTIGS = (
    ContigTarget(
        file="organelle_pfal3D7_mito.json",
        organism="Plasmodium falciparum 3D7",
        seqid="Pf3D7_MIT_v3",
    ),
    ContigTarget(
        file="organelle_pfalNF54_mito.json",
        organism="Plasmodium falciparum NF54",
        seqid="CM019798.1",
    ),
    ContigTarget(
        file="organelle_pfalSN01_mito.json",
        organism="Plasmodium falciparum SN01",
        seqid="PfSN01_MT",
    ),
    ContigTarget(
        file="organelle_pfal7G8_mito.json",
        organism="Plasmodium falciparum 7G8",
        seqid="Pf7G8_MT",
    ),
    ContigTarget(
        file="organelle_pfal7G82019_mito.json",
        organism="Plasmodium falciparum 7G8 2019",
        seqid="CM019769.1",
    ),
)


def write_recordings(into: Path, recordings: Mapping[str, BaseModel]) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name, recorded in recordings.items():
        (into / name).write_text(recorded.model_dump_json(indent=1) + "\n")


def trim_statement(seqid: str) -> str:
    return (
        f"genes holds the served {GENOME_SEARCH} records whose sequence_id is "
        f"{seqid}; served_meta is the meta of the whole served answer"
    )


async def _contig(reader: GenomeReader, target: ContigTarget) -> ContigRecording:
    genome = await genome_answer(SITE, target.organism)
    on_sequence = [
        record
        for record in genome.records
        if record.attribute_text("sequence_id") == target.seqid
    ]
    first = first_coding_gene([GeneRow.from_record(record) for record in on_sequence])
    if first is None:
        msg = f"{target.seqid} holds no coding gene of {target.organism}"
        raise ValueError(msg)
    record = await gene_record(SITE, first.gene, [ORGANISM_ATTRIBUTE], [MODEL_TABLE])
    abbrev = GeneModel.from_record(record).organism_abbrev
    length = await reader.sequence_length(abbrev, target.seqid)
    window = await reader.window(abbrev, target.seqid, 1, length)
    return ContigRecording(
        organism=target.organism,
        abbrev=abbrev,
        seqid=target.seqid,
        length=length,
        sequence=window.sequence,
        served_meta=genome.meta.model_dump(mode="json", by_alias=True),
        genes=[record.model_dump(mode="json", by_alias=True) for record in on_sequence],
        trim=trim_statement(target.seqid),
        record=record.model_dump(mode="json", by_alias=True),
    )


async def _gene(gene: str) -> GeneRecording:
    [answer] = await locus_tag_answers(
        SITE, [gene], [*LOCATED_ATTRIBUTES, PROTEIN_ATTRIBUTE]
    )
    record = await gene_record(SITE, gene, [ORGANISM_ATTRIBUTE], [MODEL_TABLE])
    return GeneRecording(
        gene=gene,
        report=answer.model_dump(mode="json", by_alias=True),
        record=record.model_dump(mode="json", by_alias=True),
    )


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    reader = GenomeReader(get_jbrowse_client(SITE))
    recordings: dict[str, BaseModel] = {}
    try:
        recordings[GENE_FILE] = await _gene(REFERENCE)
        for target in CONTIGS:
            recordings[target.file] = await _contig(reader, target)
    finally:
        await close_all_jbrowse_clients()
        await close_all_clients()
    write_recordings(into, recordings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.out))
