from __future__ import annotations

from tests._support.record_columns_site import recorded_record_type
from veupathdb.wdk import WDKRecordType

from veupathdb_mcp.embeddings.column_index import column_entries, column_index_id


def test_each_column_and_table_is_one_entry_named_by_its_owner() -> None:
    organism = recorded_record_type("veupathdb_organism_record_type.json")

    entries = {entry.entry_id: entry.text for entry in column_entries([organism])}

    assert entries["organism/column/busco_genome"] == (
        "Organism: BUSCO Genomic. Benchmarking Universal Single-Copy Orthologs "
        "completeness score of the genome assembly"
    )
    assert entries["organism/column/genecount"] == "Organism: Genes. Total gene count"
    assert entries["organism/table/GeneCounts"] == (
        "Organism: Gene types. Columns: source_id, project_id, Gene type, "
        "Pseudogene, Count"
    )


def test_a_gene_record_type_has_no_entries() -> None:
    assert column_entries([WDKRecordType(url_segment="transcript")]) == []


def test_each_site_has_its_own_index() -> None:
    assert column_index_id("orthomcl") == "record-columns:orthomcl"
