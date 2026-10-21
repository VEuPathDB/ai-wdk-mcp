"""The served listing of a genome's pseudogene calls against a reference genome."""

from __future__ import annotations

from veupathdb_mcp.audit.pseudogene_calls import (
    FAMILY_WORDS,
    GenomePseudogeneCalls,
    pseudogene_calls_of,
)
from veupathdb_mcp.audit.pseudogene_calls_inputs import pseudogene_genomes
from veupathdb_mcp.tools.audit_tools import read_inputs, run_in_a_slot


async def audit_genome_pseudogene_calls(
    site_id: str,
    organism: str,
    reference_organism: str,
) -> GenomePseudogeneCalls:
    genomes = await read_inputs(
        site_id, pseudogene_genomes(site_id, organism, reference_organism)
    )
    return await run_in_a_slot(
        pseudogene_calls_of,
        organism,
        reference_organism,
        genomes.genome,
        genomes.reference,
    )


def description() -> str:
    quoted = [f"'{word}'" for word in FAMILY_WORDS]
    words = f"{', '.join(quoted[:-1])} and {quoted[-1]}"
    return f"""List the genes a whole genome flags as pseudogenes, each paired with a reference gene.

    Each gene the site flags as a pseudogene in the organism is paired with
    a single-copy protein-coding gene of the reference organism: by its
    ortholog group when it has one, otherwise by an identical product.
    A product that holds a listed word as a lowercase substring does not
    pair, on either side. The words are: {words}, so a
    product such as 'histone H3 variant' ('var') is left out as well.
    genes counts the organism's genes, pseudogenes those the site flags as
    pseudogenes and unflagged those it does not flag either way;
    noGeneFlagged is true when the organism has genes and the site flags
    none of them. referenceGenes and referenceUnflagged count the same for
    the reference. calls lists the paired pseudogenes, and basis
    (ORTHOLOG_GROUP or PRODUCT) names how each one paired. unpairedGenes
    lists every other pseudogene with its reason: FAMILY_WORD with the word
    its product or its reference's product holds, NO_REFERENCE or
    SEVERAL_REFERENCES; unpaired counts them by reason. The call reads the
    two genomes' gene reports and no DNA. To check one strain gene against
    one reference gene in the genome, use audit_pseudogene_call.

    Args:
        site_id: VEuPathDB site, for example 'plasmodb'.
        organism: The genome whose pseudogene calls are listed, by full
            name, for example 'Plasmodium falciparum NF54'.
        reference_organism: The genome whose coding genes they pair with,
            by full name, for example 'Plasmodium falciparum 3D7'.
    """


audit_genome_pseudogene_calls.__doc__ = description()
