"""Record the genome regions, proteins, ortholog tables, gene neighbourhoods and
length-check reads the gene-model audit tests read from QA sites.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_fixtures.py MODE [--out DIR]``.
"""

import argparse
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import (
    GenomeReader,
    close_all_jbrowse_clients,
    get_jbrowse_client,
)
from veupathdb.testing.wdk_credentials import act_as_the_test_account
from veupathdb.wdk import WDKAnswer, WDKRecordInstance, close_all_clients

from veupathdb_mcp.audit import (
    GENE_ATTRIBUTES,
    LENGTH_MAX_FLANK,
    MODEL_TABLE,
    ORGANISM_ATTRIBUTE,
    ORTHOLOG_TABLE,
    GeneModel,
    OrthologRow,
    call_length,
    gene_record,
    locus_tag_answers,
    proteins_of,
    region_answer,
    rows_of,
)

FIXTURES = Path(__file__).resolve().parent.parent / "tests/unit/audit/fixtures"
LOCATION = ["sequence_id", "start_min", "end_max", "strand_plus_minus"]
PAD = 3000

type Strand = Literal["+", "-"]


class Region(BaseModel):
    model_config = ConfigDict(frozen=True)

    seqid: str
    start: int
    end: int
    strand: Strand
    sequence: str
    cds: list[tuple[int, int]]


class ProteinRegion(Region):
    model_protein: str
    reference_protein: str | None = None


class GeneLocation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    sequence_id: str
    start_min: int
    end_max: int
    strand_plus_minus: Strand


class ReferenceTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    gene: str


class StrainTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    abbrev: str
    seqid: str
    start: int
    end: int
    strand: Strand
    pad: int = PAD

    @property
    def padded(self) -> tuple[int, int]:
        return self.start - self.pad, self.end + self.pad


class ProteinTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    gene: str
    reference: bool = False


class OrthologTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    gene: str


class NeighbourTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    organism: str
    seqid: str
    start: int
    end: int


class LengthTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    gene: str
    proteins: list[str] = []


class LengthWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gene: str
    records: list[JsonValue]
    gene_answers: list[JsonValue]
    row_answers: list[JsonValue]
    protein_answers: list[JsonValue]
    contig_length: int
    window_start: int
    window: str


class Recording(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    references: list[ReferenceTarget] = []
    strains: list[StrainTarget] = []
    proteins: list[ProteinTarget] = []
    orthologs: list[OrthologTarget] = []
    neighbourhoods: list[NeighbourTarget] = []
    lengths: list[LengthTarget] = []


MODES: dict[str, Recording] = {
    "pseudogene": Recording(
        site="plasmodb",
        references=[
            ReferenceTarget(file="pfal3D7_piga.json", gene="PF3D7_1032400"),
            ReferenceTarget(file="pfal3D7_tert.json", gene="PF3D7_1314200"),
        ],
        strains=[
            StrainTarget(
                file="pfalNF54_piga.json",
                abbrev="pfalNF54",
                seqid="VBRF01000019.1",
                start=1063699,
                end=1065985,
                strand="-",
            ),
            StrainTarget(
                file="pfalDd2_tert.json",
                abbrev="pfalDd2",
                seqid="PfDd2_13",
                start=623981,
                end=631535,
                strand="+",
            ),
        ],
    ),
    "selenocysteine": Recording(
        site="toxodb",
        references=[
            ReferenceTarget(file="tgonME49_selk.json", gene="TGME49_316600"),
        ],
        strains=[
            StrainTarget(
                file="tgonGT1_selk.json",
                abbrev="tgonGT1",
                seqid="TGGT1_chrXI",
                start=5359280,
                end=5361636,
                strand="+",
                pad=0,
            ),
        ],
        proteins=[
            ProteinTarget(file="tgonGT1_selk.json", gene="TGGT1_316600"),
            ProteinTarget(
                file="tgonME49_selk.json", gene="TGME49_316600", reference=True
            ),
        ],
    ),
    "context": Recording(
        site="plasmodb",
        orthologs=[
            OrthologTarget(file="pfal3D7_piga_orthologs.json", gene="PF3D7_1032400")
        ],
        neighbourhoods=[
            NeighbourTarget(
                file="pfal3D7_piga_neighbours.json",
                organism="Plasmodium falciparum 3D7",
                seqid="Pf3D7_10_v3",
                start=1290000,
                end=1320000,
            )
        ],
    ),
    "length": Recording(
        site="plasmodb",
        lengths=[
            LengthTarget(
                file="pcynM_pkac_length.json",
                gene="PcyM_0736700",
                proteins=["PCYB_074210"],
            )
        ],
    ),
}


class ServedTable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rows: list[JsonValue] = Field(validation_alias=ORTHOLOG_TABLE)


async def _reference(site: str, reader: GenomeReader, gene: ReferenceTarget) -> Region:
    record = await gene_record(
        site, gene.gene, [*LOCATION, ORGANISM_ATTRIBUTE], [MODEL_TABLE]
    )
    where = GeneLocation.model_validate(record.attributes)
    model = GeneModel.from_record(record)
    window = await reader.window(
        model.organism_abbrev, where.sequence_id, where.start_min, where.end_max
    )
    return Region(
        seqid=window.seqid,
        start=window.start,
        end=window.end,
        strand=where.strand_plus_minus,
        sequence=window.sequence,
        cds=[(part.start, part.end) for part in model.cds],
    )


async def _strain(reader: GenomeReader, gene: StrainTarget) -> Region:
    start, end = gene.padded
    window = await reader.window(gene.abbrev, gene.seqid, start, end)
    return Region(
        seqid=window.seqid,
        start=window.start,
        end=window.end,
        strand=gene.strand,
        sequence=window.sequence,
        cds=[],
    )


def with_proteins(
    regions: dict[str, Region], targets: list[ProteinTarget], found: dict[str, str]
) -> dict[str, Region]:
    joined = dict(regions)
    for target in targets:
        protein = found[target.gene]
        joined[target.file] = ProteinRegion(
            **regions[target.file].model_dump(),
            model_protein=protein,
            reference_protein=protein if target.reference else None,
        )
    return joined


def write_regions(into: Path, regions: dict[str, Region]) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name, region in regions.items():
        (into / name).write_text(region.model_dump_json(exclude_none=True) + "\n")


def write_served(into: Path, bodies: Mapping[str, list[JsonValue]]) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        (into / name).write_text(json.dumps(body, indent=1) + "\n")


def write_lengths(into: Path, recordings: Mapping[str, LengthWire]) -> None:
    into.mkdir(parents=True, exist_ok=True)
    for name, recorded in recordings.items():
        (into / name).write_text(recorded.model_dump_json(indent=1) + "\n")


def _served(record: WDKRecordInstance) -> JsonValue:
    return record.model_dump(mode="json", by_alias=True)


def _answers(answers: list[WDKAnswer]) -> list[JsonValue]:
    return [answer.model_dump(mode="json", by_alias=True) for answer in answers]


async def _length(site: str, reader: GenomeReader, target: LengthTarget) -> LengthWire:
    gene_answers = await locus_tag_answers(site, [target.gene], GENE_ATTRIBUTES)
    orthologs = await gene_record(site, target.gene, [], [ORTHOLOG_TABLE])
    table = ServedTable.model_validate(orthologs.tables).rows
    named = {OrthologRow.model_validate(served).gene for served in table}
    row_answers = await locus_tag_answers(
        site, sorted({target.gene, *named}), GENE_ATTRIBUTES
    )
    rows = [r for answer in row_answers for r in rows_of(answer, "GeneByLocusTag")]
    row = next(r for r in rows if r.gene == target.gene)
    reference = call_length([row], rows).reference
    genes = [target.gene, *([reference.gene] if reference else []), *target.proteins]
    protein_answers = await locus_tag_answers(site, genes, ["protein_sequence"])
    model_record = await gene_record(
        site, target.gene, [ORGANISM_ATTRIBUTE], [MODEL_TABLE]
    )
    abbrev = GeneModel.from_record(model_record).organism_abbrev
    contig_length = await reader.sequence_length(abbrev, row.sequence_id)
    window = await reader.window(
        abbrev,
        row.sequence_id,
        row.start - LENGTH_MAX_FLANK,
        row.end + LENGTH_MAX_FLANK,
    )
    return LengthWire(
        gene=target.gene,
        records=[_served(orthologs), _served(model_record)],
        gene_answers=_answers(gene_answers),
        row_answers=_answers(row_answers),
        protein_answers=_answers(protein_answers),
        contig_length=contig_length,
        window_start=window.start,
        window=window.sequence,
    )


async def _context(site: str, recording: Recording) -> dict[str, list[JsonValue]]:
    bodies: dict[str, list[JsonValue]] = {}
    for target in recording.orthologs:
        record = await gene_record(site, target.gene, [], [ORTHOLOG_TABLE])
        bodies[target.file] = ServedTable.model_validate(record.tables).rows
    for place in recording.neighbourhoods:
        answer = await region_answer(
            site, place.organism, place.seqid, place.start, place.end
        )
        bodies[place.file] = [
            record.model_dump(mode="json", by_alias=True) for record in answer.records
        ]
    return bodies


async def record(mode: str, into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    recording = MODES[mode]
    site = recording.site
    reader = GenomeReader(get_jbrowse_client(site))
    regions: dict[str, Region] = {}
    try:
        for reference in recording.references:
            regions[reference.file] = await _reference(site, reader, reference)
        for strain in recording.strains:
            regions[strain.file] = await _strain(reader, strain)
        genes = [target.gene for target in recording.proteins]
        found = await proteins_of(site, genes)
        context = await _context(site, recording)
        lengths = {t.file: await _length(site, reader, t) for t in recording.lengths}
    finally:
        await close_all_jbrowse_clients()
        await close_all_clients()
    write_regions(into, with_proteins(regions, recording.proteins, found))
    write_served(into, context)
    write_lengths(into, lengths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(MODES))
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.mode, arguments.out))
