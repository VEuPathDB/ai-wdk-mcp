"""The served evidence tools: what a site serves for a gene, and a genome's provenance."""

from __future__ import annotations

from veupathdb_mcp.audit.evidence import GeneEvidence, GenomeProvenance
from veupathdb_mcp.audit.evidence_inputs import gene_evidence, genome_provenance
from veupathdb_mcp.tools.audit_tools import read_inputs


async def audit_gene_evidence(site_id: str, gene: str) -> GeneEvidence:
    """Return the evidence a site serves on a gene's record, without a verdict.

    transcripts are the gene's transcripts with their protein lengths.
    pdbHits are the PDB structures similar to each transcript's protein, one
    per structure with its chains, identity and e-value; the site serves at
    most 20 rows per transcript, one per chain, so a structure past them is
    not listed, and it serves no residue positions. proteinCoveredPercent is
    the site's own "% of VEuPathDB protein covered"; the site serves 0 for
    some near-identical hits (the gene's own crystal structures among them),
    so 0 does not mean no overlap. peptides are the distinct mass-spec
    peptides with their protein start and end on their own transcript and
    the experiments that saw them. alphafold holds the AlphaFold models of
    the UniProt entries the site links to the gene, directly or by sequence
    similarity (source says which); first and last are residues of that
    entry, not of the gene's protein. linkouts are the site's
    cross-references (database and id); seqedits are the sequence edits the
    site lists in the gene's region. comments, pubmed and notes count the
    user comments, PubMed articles and annotator notes. phenotypes holds
    the phenotype tables named for the gene's organism (the name starts
    with its abbreviation), each with its rows. A table with no row does not
    mean the screen has no result for the gene: the site may serve a
    screen's results in EdaPhenotypeGraphsDataTable, each row named by its
    dataset_id. unprefixedTables holds the phenotype tables named for no
    organism and offered on every organism of the site, each with its rows;
    an empty one says nothing about this gene or its organism. unserved
    names the evidence tables the site does not declare or did not answer.
    Reads: the record of the id; the site's gene record type (once per site
    and process); one gene record read with every evidence table the type
    declares.
    geneIds pairs each id given with the site's own gene id it names (the
    same id, an alias or a previous id its gene record read resolves, a
    transcript id the site's text search names, or the one gene whose own id
    is the id with a ":" qualifier added); every other gene field holds that
    id. Each id given costs one gene record read; an id no record names adds
    one text search and one record read of the gene it names. Resolving ids
    uploads no gene list, and a refusal names an id that names several genes.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        gene: The gene whose record is read.
    """
    return await read_inputs(site_id, gene_evidence(site_id, gene))


async def audit_genome_provenance(site_id: str, organism: str) -> GenomeProvenance:
    """Return where a genome's assembly and annotation come from, as the site states.

    genomeVersion is the site's "Genome Version/Assembly ID" (an assembly
    accession and version, or a date when the site gives no accession),
    genomeSource its source, annotationSource and annotationVersion the
    structural annotation (null when the site states none), databaseVersion
    the site's "Genome version" date, and buildIntroduced and
    buildLatestUpdate the site builds that loaded and last updated the
    genome (null when the site serves build 0, which names no build).
    recordId is the organism record's id on the site (a taxon id such as
    NCBITAXON_5843, not the organism abbreviation), organism its full name,
    referenceStrain whether the site marks it as its species' reference
    strain, and ncbiTaxon its NCBI taxon id (null when the site serves
    none).

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        organism: The organism's full name, for example 'Plasmodium falciparum NF54'.
    """
    return await read_inputs(site_id, genome_provenance(site_id, organism))
