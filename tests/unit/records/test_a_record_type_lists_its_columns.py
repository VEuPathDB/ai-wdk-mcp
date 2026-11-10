from __future__ import annotations

import pytest

from veupathdb_mcp.record_fields import ColumnInfo
from veupathdb_mcp.records import UnreadableRecordError, record_columns

pytestmark = pytest.mark.usefixtures("catalog")


async def test_the_organism_record_lists_its_busco_and_gene_count_columns() -> None:
    listed = await record_columns("veupathdb", "organism")

    by_name = {column.name: column for column in listed.columns}
    assert by_name["busco_genome"] == ColumnInfo(
        name="busco_genome",
        display_name="BUSCO Genomic",
        help=(
            "Benchmarking Universal Single-Copy Orthologs completeness score of "
            "the genome assembly"
        ),
    )
    assert by_name["genecount"].display_name == "Genes"
    assert [table.name for table in listed.tables] == [
        "SequenceCounts",
        "GeneCounts",
        "GenomeSequencingAndAnnotationAttribution",
        "Searches",
    ]


async def test_the_organism_record_lists_the_searches_that_return_it() -> None:
    listed = await record_columns("veupathdb", "organism")

    assert [search.name for search in listed.searches] == [
        "AllOrganisms",
        "GenomeDataTypes",
        "SitemapGenomeDataTypes",
        "GeneMetrics",
        "OrganismsByText",
    ]


async def test_orthomcl_lists_its_proteome_summary_table() -> None:
    listed = await record_columns("orthomcl", "helper")

    summary = next(table for table in listed.tables if table.name == "DataSummary")
    assert summary.display_name == "Data Summary"
    assert [column.display_name for column in summary.columns][7:11] == [
        "Proteome Version",
        "# Proteins",
        "# Proteins in Groups",
        "# Ortholog Groups",
    ]


async def test_a_gene_record_type_is_refused_by_name() -> None:
    with pytest.raises(UnreadableRecordError, match="strategy"):
        await record_columns("veupathdb", "transcript")


async def test_an_unknown_record_type_is_refused_with_the_ones_there_are() -> None:
    with pytest.raises(UnreadableRecordError, match="organism"):
        await record_columns("veupathdb", "organisms")
