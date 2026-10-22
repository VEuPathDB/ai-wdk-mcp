"""Record the gene model, RNA-seq junctions, genome window and proteins the intron
support audit tests read from QA sites.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python -m scripts.record_audit_introns TARGET [--out DIR]``.
"""

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, JsonValue
from scripts.record_audit_fixtures import (
    FIXTURES,
    ServedTable,
    act_as_the_test_account,
    served_answers,
)
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import GenomeReader, JBrowseClient, TabixReader
from veupathdb.wdk import close_all_clients, get_site

from veupathdb_mcp.audit.gene_models import (
    MODEL_TABLE,
    ORGANISM_ATTRIBUTE,
    GeneModel,
    gene_record,
)
from veupathdb_mcp.audit.genes import (
    GENE_ATTRIBUTES,
    ORTHOLOG_TABLE,
    OrthologGroup,
    OrthologRow,
    locus_tag_answers,
    rows_of,
)
from veupathdb_mcp.audit.introns_inputs import (
    genome_region,
    junction_region,
    ortholog_choice,
)


class TrackLists(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        self.bodies.append(await response.aread())
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class IntronTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    gene: str
    file: str


class IntronWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str
    gene: str
    gene_answers: list[JsonValue]
    model_record: JsonValue
    protein_answers: list[JsonValue]
    junction_tracks: JsonValue
    junction_seqid: str
    junction_region: tuple[int, int]
    junction_lines: dict[str, list[str]]
    window_start: int
    window: str
    ortholog_record: JsonValue
    ortholog_protein_answers: list[JsonValue]


TARGETS: dict[str, IntronTarget] = {
    "pkac": IntronTarget(
        site="plasmodb", gene="PcyM_0736700", file="introns_pcynM_pkac.json"
    ),
    "dmaw": IntronTarget(
        site="fungidb", gene="Afu2g18040", file="introns_afumAf293_dmaw.json"
    ),
}


def write_wire(into: Path, name: str, wire: IntronWire) -> None:
    into.mkdir(parents=True, exist_ok=True)
    (into / name).write_text(wire.model_dump_json(indent=1) + "\n")


async def record(target: IntronTarget, into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    site, gene = target.site, target.gene
    recorder = TrackLists(httpx.AsyncHTTPTransport())
    client = JBrowseClient(base_url=get_site(site).web_base_url, transport=recorder)
    try:
        gene_answers = await locus_tag_answers(site, [gene], GENE_ATTRIBUTES)
        [row] = rows_of(gene_answers[0], "GeneByLocusTag")
        model_record = await gene_record(
            site, gene, [ORGANISM_ATTRIBUTE], [MODEL_TABLE]
        )
        abbrev = GeneModel.from_record(model_record).organism_abbrev
        protein_answers = await locus_tag_answers(site, [gene], ["protein_sequence"])
        tracks = await client.junction_tracks(abbrev)
        listed = json.loads(recorder.bodies[-1])
        region = junction_region(row)
        reader = TabixReader(client)
        lines = {
            track.data_path: await reader.lines(track, row.sequence_id, *region)
            for track in tracks
        }
        window = await GenomeReader(client).window(
            abbrev, row.sequence_id, *genome_region(row)
        )
        orthologs = await gene_record(site, gene, [], [ORTHOLOG_TABLE])
        table = [
            OrthologRow.model_validate(served)
            for served in ServedTable.model_validate(orthologs.tables).rows
        ]
        named = list(
            ortholog_choice(
                OrthologGroup(gene=gene, members=[r for r in table if r.gene != gene]),
                row,
            )
        )
        ortholog_answers = await locus_tag_answers(site, named, ["protein_sequence"])
    finally:
        await client.close()
        await close_all_clients()
    write_wire(
        into,
        target.file,
        IntronWire(
            site=site,
            gene=gene,
            gene_answers=served_answers(gene_answers),
            model_record=model_record.model_dump(mode="json", by_alias=True),
            protein_answers=served_answers(protein_answers),
            junction_tracks=listed,
            junction_seqid=row.sequence_id,
            junction_region=region,
            junction_lines=lines,
            window_start=window.start,
            window=window.sequence,
            ortholog_record=orthologs.model_dump(mode="json", by_alias=True),
            ortholog_protein_answers=served_answers(ortholog_answers),
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=sorted(TARGETS))
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(TARGETS[arguments.target], arguments.out))
