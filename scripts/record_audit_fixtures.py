"""Record the genome regions and proteins the gene-model audit tests read from QA sites.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_fixtures.py MODE [--out DIR]``.
"""

import argparse
import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import (
    GenomeReader,
    close_all_jbrowse_clients,
    get_jbrowse_client,
)
from veupathdb.testing.wdk_credentials import act_as_the_test_account
from veupathdb.wdk import StrategyAPI, close_all_clients, get_site, get_wdk_client

from veupathdb_mcp.audit import (
    MODEL_TABLE,
    ORGANISM_ATTRIBUTE,
    GeneModel,
    proteins_of,
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


class Recording(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    references: list[ReferenceTarget] = []
    strains: list[StrainTarget] = []
    proteins: list[ProteinTarget] = []


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
}


async def _reference(
    site: str, api: StrategyAPI, reader: GenomeReader, gene: ReferenceTarget
) -> Region:
    record = await api.get_single_record(
        "gene",
        [
            {"name": "source_id", "value": gene.gene},
            {"name": "project_id", "value": get_site(site).project_id},
        ],
        attributes=[*LOCATION, ORGANISM_ATTRIBUTE],
        tables=[MODEL_TABLE],
    )
    where = GeneLocation.model_validate(record.attributes)
    model = GeneModel.from_record(record)
    window = await reader.window(
        model.organism, where.sequence_id, where.start_min, where.end_max
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


async def record(mode: str, into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    recording = MODES[mode]
    site = recording.site
    api = StrategyAPI(get_wdk_client(site))
    reader = GenomeReader(get_jbrowse_client(site))
    regions: dict[str, Region] = {}
    try:
        for reference in recording.references:
            regions[reference.file] = await _reference(site, api, reader, reference)
        for strain in recording.strains:
            regions[strain.file] = await _strain(reader, strain)
        genes = [target.gene for target in recording.proteins]
        found = await proteins_of(site, genes)
    finally:
        await close_all_jbrowse_clients()
        await close_all_clients()
    write_regions(into, with_proteins(regions, recording.proteins, found))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(MODES))
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.mode, arguments.out))
