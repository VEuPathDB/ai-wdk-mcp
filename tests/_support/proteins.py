from typing import Literal

from veupathdb_mcp.audit.genes import GeneRow

PROTEIN = (
    "MMFPCDVENWCTHCDQQDIDVQCWEIWCWWPCICVFLQFVEWLVGEWWHNEVDWCYHSVQMRWRNLIGIDWLTSMRLYDETQ"
    "GMFSQCDVWMMNYSWRDDKSDCLWRLPNARNGYESCHLFIPPSDGRPVKFQVKQNPIFDGFIIASWGKLAFQVNYWMFTYC"
    "RVPPPPESPCHDHRGEMYCEAWFVENYADHYPFKNYN"
)

CODON = {
    "A": "GCT",
    "C": "TGT",
    "D": "GAT",
    "E": "GAA",
    "F": "TTT",
    "G": "GGT",
    "H": "CAT",
    "I": "ATT",
    "K": "AAA",
    "L": "TTA",
    "M": "ATG",
    "N": "AAT",
    "P": "CCT",
    "Q": "CAA",
    "R": "AGA",
    "S": "TCT",
    "T": "ACT",
    "V": "GTT",
    "W": "TGG",
    "Y": "TAT",
}


def back_translate(protein: str) -> str:
    return "".join(CODON[a] for a in protein)


def row(
    gene: str,
    organism: str,
    length: int | None,
    *,
    start: int = 100001,
    strand: Literal["+", "-"] = "+",
) -> GeneRow:
    return GeneRow(
        gene=gene,
        organism=organism,
        ortholog_group="OG7_0000001",
        protein_length=length,
        name="",
        product="conserved protein",
        sequence_id=f"{gene}_contig",
        start=start,
        end=start + 3 * (length or 100) + 2,
        strand=strand,
        pseudo=False,
        gene_type="protein coding gene",
    )
