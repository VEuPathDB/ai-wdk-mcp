from veupathdb_mcp.audit.evidence import requested_tables

PLASMODB_TABLES = [
    "GeneModelDump",
    "GeneTranscripts",
    "Seqedits",
    "EdaPhenotypeGraphsDataTable",
    "PhenotypeScoreGraphsDataTable",
    "pberANKA_phenotype_Bushnell_functional_profiling_RSRC_Phenotype",
    "pfal3D7_phenotype_pB_mutagenesis_MIS_MFS_RSRC",
    "UserDatasetsEdaPhenotype",
    "EdaPhenotypeDatasets",
    "PhenotypeScoreGraphs",
    "eQTLPhenotypeGraphs",
    "PhenotypeScore",
    "Notes",
    "UserComments",
    "MassSpec",
    "MassSpecDownload",
    "RodMalPhenotype",
    "Orthologs",
    "PubMed",
    "GeneLinkouts",
    "PdbSimilarities",
    "AlphaFoldLinkouts",
]


def test_a_gene_record_asks_the_declared_evidence_and_screen_tables() -> None:
    assert requested_tables(PLASMODB_TABLES) == [
        "GeneTranscripts",
        "Seqedits",
        "EdaPhenotypeGraphsDataTable",
        "PhenotypeScoreGraphsDataTable",
        "pberANKA_phenotype_Bushnell_functional_profiling_RSRC_Phenotype",
        "pfal3D7_phenotype_pB_mutagenesis_MIS_MFS_RSRC",
        "PhenotypeScore",
        "Notes",
        "UserComments",
        "MassSpecDownload",
        "RodMalPhenotype",
        "PubMed",
        "GeneLinkouts",
        "PdbSimilarities",
        "AlphaFoldLinkouts",
    ]


def test_a_table_the_site_does_not_declare_is_not_asked() -> None:
    assert requested_tables(
        ["Notes", "PhenotypeGraphs", "PhenotypeGraphsDataTable", "Phenotype"]
    ) == ["Notes", "PhenotypeGraphsDataTable", "Phenotype"]


def test_phenotype_image_galleries_are_not_screens() -> None:
    assert requested_tables(
        [
            "afumAf293_TF_KO_Image_NAFeaturePhenotypeImage_RSRC_PhenotypeImages",
            "ncraOR74A_phenotype_knockout_mutants_RSRC_Phenotype",
            "CrisprPhenotypeGraphsDataTable",
        ]
    ) == [
        "ncraOR74A_phenotype_knockout_mutants_RSRC_Phenotype",
        "CrisprPhenotypeGraphsDataTable",
    ]
