from tests._support.audit_site import own_id
from tests._support.evidence_site import (
    DMAW,
    K13,
    PIGA,
    declared,
    gene_record,
)
from veupathdb.wdk import WDKRecordInstance

from veupathdb_mcp.audit.evidence import GeneEvidence, PhenotypeScreen

PB_SCREEN = "pfal3D7_phenotype_pB_mutagenesis_MIS_MFS_RSRC"
PB_DATASET = "PlasmoDB_pfal3D7_pB_mutagenesis_MIS_MFS_Phenotype_RSRC"


def evidence(gene: str, name: str, site: str) -> GeneEvidence:
    return GeneEvidence.from_record(own_id(gene), gene_record(name), declared(site))


def k13() -> GeneEvidence:
    return evidence(K13, "evidence_pfal3D7_k13.json", "plasmodb")


def test_an_empty_screen_table_and_its_eda_results_are_both_served() -> None:
    gene = k13()
    unprefixed = {table.table: table.rows for table in gene.unprefixed_tables}

    assert gene.phenotypes == [PhenotypeScreen(table=PB_SCREEN, rows=[])]
    assert unprefixed["EdaPhenotypeGraphsDataTable"][0] == {
        "dataset_id": PB_DATASET,
        "variable": "Mutagenesis Index Score",
        "value": "0.1220",
    }


def test_the_tables_named_for_no_organism_are_served_apart() -> None:
    unprefixed = {table.table: table.rows for table in k13().unprefixed_tables}

    assert list(unprefixed) == [
        "EdaPhenotypeGraphsDataTable",
        "PhenotypeScoreGraphsDataTable",
        "PhenotypeScore",
        "RodMalPhenotype",
    ]
    assert unprefixed["PhenotypeScoreGraphsDataTable"] == []
    assert unprefixed["RodMalPhenotype"][0]["pubmed_rodmal_link"] == "33173001"
    assert unprefixed["RodMalPhenotype"][0]["life_cycle_stage"] == "asexual"


def test_a_fungal_gene_has_no_own_screen_and_its_curated_rows_are_unprefixed() -> None:
    dmaw = evidence(DMAW, "evidence_afumAf293_dmaw.json", "fungidb")
    unprefixed = {table.table: table.rows for table in dmaw.unprefixed_tables}

    assert dmaw.phenotypes == []
    assert sorted(unprefixed) == [
        "CGD_CuratedPhenotypes",
        "EdaPhenotypeGraphsDataTable",
        "PHI-base_curated_phenotype_NAFeaturePhenotypeGeneric_RSRC_Phenotype",
        "Phenotype",
        "PhenotypeMagnaporthe",
        "PhenotypeScore",
    ]
    assert (
        unprefixed["CGD_CuratedPhenotypes"],
        unprefixed["PhenotypeMagnaporthe"],
    ) == (
        [],
        [],
    )
    assert {
        "dataset_id": "FungiDB_VEuPathDB_curated_phenotype_Phenotype_RSRC",
        "variable": "Pubmed ID",
        "value": "15933009",
    } in unprefixed["EdaPhenotypeGraphsDataTable"]


def test_a_screen_of_another_organism_is_not_served() -> None:
    gene = evidence(PIGA, "evidence_pfal3D7_piga.json", "plasmodb")
    tables = [s.table for s in [*gene.phenotypes, *gene.unprefixed_tables]]

    assert [s.table for s in gene.phenotypes] == [PB_SCREEN]
    assert "pberANKA_phenotype_Bushnell_functional_profiling_RSRC_Phenotype" not in (
        tables
    )
    assert "pknoH_phenotype_piggyBac_mutagenesis_HME_MIS_OIS_RSRC" not in tables


def test_an_abbreviation_with_an_underscore_keeps_its_own_screen() -> None:
    own = "aaegLVP_AGWG_phenotype_insecticide_RSRC"
    other = "aaegLVP_phenotype_insecticide_RSRC"
    record = WDKRecordInstance.model_validate(
        {
            "attributes": {"organismAbbrev": "aaegLVP_AGWG"},
            "tables": {own: [{"score": "0.5"}], other: []},
        }
    )

    gene = GeneEvidence.from_record(own_id("AAEL000001"), record, [own, other])

    assert gene.phenotypes == [PhenotypeScreen(table=own, rows=[{"score": "0.5"}])]
    assert gene.unprefixed_tables == []
