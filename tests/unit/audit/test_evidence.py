import pytest
from pydantic import ValidationError
from tests._support.audit_site import own_id
from tests._support.evidence_site import (
    DMAW,
    GLO1,
    K13,
    NF54,
    PIGA,
    declared,
    gene_record,
    genome_answer,
)
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit.evidence import (
    AlphaFoldModel,
    GeneEvidence,
    GeneTranscript,
    Linkout,
    PdbHit,
    Peptide,
    provenance_of,
)


def evidence(gene: str, name: str, site: str) -> GeneEvidence:
    return GeneEvidence.from_record(own_id(gene), gene_record(name), declared(site))


def piga() -> GeneEvidence:
    return evidence(PIGA, "evidence_pfal3D7_piga.json", "plasmodb")


def k13() -> GeneEvidence:
    return evidence(K13, "evidence_pfal3D7_k13.json", "plasmodb")


def glo1() -> GeneEvidence:
    return evidence(GLO1, "evidence_lmajFriedlin_glo1.json", "tritrypdb")


def test_pdb_hits_are_one_per_structure_with_their_chains() -> None:
    hits = piga().pdb_hits

    assert [(hit.pdb_id, hit.chains) for hit in hits] == [
        ("3mbo", ["3mbo_D", "3mbo_C", "3mbo_B", "3mbo_A"]),
        ("2jjm", [f"2jjm_{chain}" for chain in "LKJIHGFEDCBA"]),
        ("5d01", ["5d01_B", "5d01_A"]),
        ("5d00", ["5d00_B", "5d00_A"]),
    ]
    assert hits[0] == PdbHit(
        transcript="PF3D7_1032400.1",
        pdb_id="3mbo",
        title="Glycosyltransferase, group 1 family",
        taxon="Bacillus anthracis",
        identity=24,
        protein_covered_percent=53,
        evalue=1.43e-12,
        chains=["3mbo_D", "3mbo_C", "3mbo_B", "3mbo_A"],
    )


def test_the_served_structures_of_dmaw_and_glo1_are_their_crystal_structures() -> None:
    dmaw = evidence(DMAW, "evidence_afumAf293_dmaw.json", "fungidb")
    exact = [
        (h.pdb_id, h.identity, h.protein_covered_percent, h.evalue)
        for h in dmaw.pdb_hits
    ]
    assert exact[-2:] == [("3i4z", 98, 0, 0.0), ("3i4x", 98, 0, 0.0)]
    assert dmaw.alphafold == []

    glyoxalase = [
        (hit.transcript, hit.identity, len(hit.chains), hit.evalue)
        for hit in glo1().pdb_hits
        if hit.pdb_id == "2c21"
    ]
    assert glyoxalase == [
        ("LmjF.35.3010.2:mRNA", 100, 6, 2.5e-101),
        ("LmjF.35.3010.1:mRNA", 99, 6, 1.26e-99),
    ]


def test_the_site_serves_no_protein_coverage_for_the_genes_own_structure() -> None:
    own = next(hit for hit in k13().pdb_hits if hit.pdb_id == "4zgc")

    assert (own.identity, own.protein_covered_percent, own.chains) == (
        100,
        0,
        ["4zgc_B", "4zgc_A"],
    )


def test_peptides_are_distinct_spans_with_their_experiments() -> None:
    peptides = k13().peptides

    assert len(peptides) == 59
    assert peptides[0] == Peptide(
        transcript="PF3D7_1343700.1",
        sequence="TKANSISNFSMTYDR",
        start=8,
        end=22,
        experiments=["Blood stage phospho- and total proteome (3D7)"],
        spectra=1,
    )
    assert len({e for p in peptides for e in p.experiments}) == 18


def test_cross_references_counts_and_screens_are_read_as_served() -> None:
    gene = k13()

    assert gene.alphafold == [
        AlphaFoldModel(
            uniprot_id="Q8IDQ2",
            source="SWISSPROT direct link",
            first=1,
            last=726,
            length=726,
        )
    ]
    assert len(gene.linkouts) == 43
    assert Linkout(database="PDB", external_id="4ZGC") in gene.linkouts
    assert (gene.comments, gene.pubmed, gene.notes) == (9, 44, 2)
    assert gene.unserved == []


def test_a_gene_with_empty_tables_has_empty_lists() -> None:
    gene = piga()

    assert (gene.peptides, gene.seqedits) == ([], [])
    assert (gene.comments, gene.pubmed, gene.notes) == (0, 2, 0)


def test_the_transcripts_are_read_with_their_protein_lengths() -> None:
    assert glo1().transcripts == [
        GeneTranscript(
            transcript_id="LmjF.35.3010.1:mRNA",
            transcript_type="mRNA",
            protein_length=249,
            exon_count=1,
        ),
        GeneTranscript(
            transcript_id="LmjF.35.3010.2:mRNA",
            transcript_type="mRNA",
            protein_length=141,
            exon_count=1,
        ),
    ]


def test_a_table_not_declared_or_not_answered_is_unserved() -> None:
    record = gene_record("evidence_pfal3D7_piga.json")
    erred = WDKRecordInstance.model_validate(
        {**record.model_dump(by_alias=True), "tableErrors": ["GeneLinkouts"]}
    )
    sites = [name for name in declared("plasmodb") if name != "MassSpecDownload"]

    gene = GeneEvidence.from_record(own_id(PIGA), erred, sites)

    assert gene.unserved == ["GeneLinkouts", "MassSpecDownload"]


def test_a_requested_table_missing_from_the_record_is_unserved() -> None:
    record = gene_record("evidence_pfal3D7_piga.json")
    tables = {
        name: rows
        for name, rows in record.tables.items()
        if name not in {"Notes", "PhenotypeScore"}
    }
    broken = WDKRecordInstance.model_validate(
        {**record.model_dump(by_alias=True), "tables": tables}
    )

    gene = GeneEvidence.from_record(own_id(PIGA), broken, declared("plasmodb"))

    assert gene.unserved == ["Notes", "PhenotypeScore"]
    assert "PhenotypeScore" not in [table.table for table in gene.unprefixed_tables]


def test_a_peptide_stands_on_its_own_transcript_coordinates() -> None:
    elvadmr = [
        (peptide.transcript, peptide.start, peptide.end)
        for peptide in glo1().peptides
        if peptide.sequence == "ELVADMR"
    ]

    assert sorted(elvadmr) == [
        ("LmjF.35.3010.1:mRNA", 195, 201),
        ("LmjF.35.3010.2:mRNA", 87, 93),
    ]


def test_evidence_is_served_in_camel_case() -> None:
    served = piga().model_dump(by_alias=True)

    assert sorted(served) == [
        "alphafold",
        "comments",
        "gene",
        "geneIds",
        "linkouts",
        "notes",
        "pdbHits",
        "peptides",
        "phenotypes",
        "pubmed",
        "seqedits",
        "transcripts",
        "unprefixedTables",
        "unserved",
    ]
    assert sorted(served["pdbHits"][0]) == [
        "chains",
        "evalue",
        "identity",
        "pdbId",
        "proteinCoveredPercent",
        "taxon",
        "title",
        "transcript",
    ]
    assert served["alphafold"][0]["uniprotId"] == "Q8IJ83"
    assert served["linkouts"][0] == {
        "database": "Ares Lab Genome Browser",
        "externalId": "PF10_0316",
    }


def test_provenance_carries_the_served_assembly_and_annotation() -> None:
    answer = genome_answer()
    nf54 = provenance_of(answer, NF54)
    reference = provenance_of(answer, "Plasmodium falciparum 3D7")

    assert nf54 is not None
    assert reference is not None
    assert nf54.model_dump() == {
        "record_id": "NCBITAXON_5843",
        "organism": NF54,
        "genome_source": "INSDC",
        "genome_version": "GCA_009761475.1",
        "annotation_source": None,
        "annotation_version": None,
        "database_version": "2019-12-17",
        "build_introduced": 55,
        "build_latest_update": 55,
        "reference_strain": False,
        "ncbi_taxon": "5843",
    }
    assert (
        reference.genome_version,
        reference.annotation_source,
        reference.annotation_version,
        reference.reference_strain,
        reference.build_introduced,
        reference.build_latest_update,
    ) == ("GCA_000002765.3", "GeneDB", "Sep 01, 2020", True, None, 71)


def test_an_organism_the_report_does_not_hold_has_no_provenance() -> None:
    assert provenance_of(genome_answer(), "Plasmodium falciparum NF55") is None


def test_evidence_whose_gene_ids_name_another_gene_is_invalid() -> None:
    served = piga().model_dump()

    with pytest.raises(ValidationError, match="geneIds resolve to"):
        GeneEvidence.model_validate({**served, "gene": K13})
