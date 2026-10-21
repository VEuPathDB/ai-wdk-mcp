"""Record the reads of the strain-model check for strain genes and their species
references on a QA site.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python scripts/record_audit_strain.py [--out DIR]``.
"""

import argparse
import asyncio
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator
from scripts.record_audit_fixtures import (
    FIXTURES,
    LengthWire,
    ServedTable,
    served_answers,
    served_body,
    write_lengths,
)
from veupathdb.devtools import use_qa_sites
from veupathdb.jbrowse import (
    GenomeReader,
    close_all_jbrowse_clients,
    get_jbrowse_client,
)
from veupathdb.testing.wdk_credentials import act_as_the_test_account
from veupathdb.wdk import close_all_clients

from veupathdb_mcp.audit import (
    GENE_ATTRIBUTES,
    LENGTH_MAX_FLANK,
    LOCATED_ATTRIBUTES,
    MODEL_TABLE,
    ORGANISM_ATTRIBUTE,
    ORTHOLOG_TABLE,
    GeneModel,
    OrthologRow,
    gene_record,
    locus_tag_answers,
    rows_of,
)

SITE = "plasmodb"


class StrainPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    reference: str
    strain: str | None = None
    organism: str | None = None

    @model_validator(mode="after")
    def _one_strain(self) -> Self:
        if (self.strain is None) == (self.organism is None):
            msg = "a pair names its strain gene or the organism to find it in"
            raise ValueError(msg)
        return self

    def strain_in(self, table: list[OrthologRow]) -> str:
        if self.strain is not None:
            return self.strain
        genes = [row.gene for row in table if row.organism == self.organism]
        if len(genes) != 1:
            msg = (
                f"the orthologs of {self.reference} name {len(genes)} genes "
                f"of {self.organism}"
            )
            raise ValueError(msg)
        return genes[0]


class StrainWire(LengthWire):
    reference: str


PAIRS = [
    StrainPair(
        file="strain_pcynM_pkac.json",
        reference="PCYB_074210",
        strain="PcyM_0736700",
    ),
    StrainPair(
        file="strain_pfalDd2_yip1.json",
        reference="PF3D7_1472100",
        organism="Plasmodium falciparum Dd2",
    ),
]


async def _pair(reader: GenomeReader, pair: StrainPair) -> StrainWire:
    orthologs = await gene_record(SITE, pair.reference, [], [ORTHOLOG_TABLE])
    table = [
        OrthologRow.model_validate(served)
        for served in ServedTable.model_validate(orthologs.tables).rows
    ]
    strain = pair.strain_in(table)
    genes = [strain, pair.reference]
    gene_answers = await locus_tag_answers(SITE, genes, LOCATED_ATTRIBUTES)
    protein_answers = await locus_tag_answers(SITE, genes, ["protein_sequence"])
    row_answers = await locus_tag_answers(
        SITE, sorted({pair.reference, *(row.gene for row in table)}), GENE_ATTRIBUTES
    )
    [row] = [
        r
        for answer in gene_answers
        for r in rows_of(answer, "GeneByLocusTag")
        if r.gene == strain
    ]
    model_record = await gene_record(SITE, strain, [ORGANISM_ATTRIBUTE], [MODEL_TABLE])
    abbrev = GeneModel.from_record(model_record).organism_abbrev
    contig_length = await reader.sequence_length(abbrev, row.sequence_id)
    window = await reader.window(
        abbrev,
        row.sequence_id,
        row.start - LENGTH_MAX_FLANK,
        row.end + LENGTH_MAX_FLANK,
    )
    return StrainWire(
        gene=strain,
        reference=pair.reference,
        records=[served_body(orthologs), served_body(model_record)],
        gene_answers=served_answers(gene_answers),
        row_answers=served_answers(row_answers),
        protein_answers=served_answers(protein_answers),
        contig_length=contig_length,
        window_start=window.start,
        window=window.sequence,
    )


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    reader = GenomeReader(get_jbrowse_client(SITE))
    try:
        wires = {pair.file: await _pair(reader, pair) for pair in PAIRS}
    finally:
        await close_all_jbrowse_clients()
        await close_all_clients()
    write_lengths(into, wires)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    arguments = parser.parse_args()
    asyncio.run(record(arguments.out))
