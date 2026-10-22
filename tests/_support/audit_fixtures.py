from pathlib import Path

from scripts.record_audit_fixtures import ProteinRegion, Region
from veupathdb.jbrowse import GenomeWindow

from veupathdb_mcp.audit.gene_ids import GeneId
from veupathdb_mcp.audit.gene_models import ModelSpans, ReadModels
from veupathdb_mcp.audit.pseudogene import CdsPart, ReferenceGene
from veupathdb_mcp.audit.served import PseudogeneInputs, SelenoproteinInputs
from veupathdb_mcp.tool_errors import ToolErrorPayload, tool_error

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"
PIGA = "PF3D7_1032400"
NF54_PIGA = "PfNF54_100037200"
NF54_PIGA_ID = "PfNF54_100037200:pseudogene"
GT1_SELK = "TGGT1_316600"
ME49_SELK = "TGME49_316600"


def load(name: str) -> Region:
    return Region.model_validate_json((FIXTURES / name).read_text())


def load_protein(name: str) -> ProteinRegion:
    return ProteinRegion.model_validate_json((FIXTURES / name).read_text())


def reference_protein(name: str) -> str:
    protein = load_protein(name).reference_protein
    assert protein is not None
    return protein


def reference_piga() -> ReferenceGene:
    ref = load("pfal3D7_piga.json")
    return ReferenceGene(
        dna=ref.sequence,
        cds=[CdsPart(start=a, end=b) for a, b in ref.cds],
        start=ref.start,
        end=ref.end,
        strand=ref.strand,
    )


def spans(gene: str, region: Region) -> ModelSpans:
    return ModelSpans(
        gene=gene,
        transcript=f"{gene}.1",
        seqid=region.seqid,
        strand=region.strand,
        exons=region.cds or [(region.start, region.end)],
        cds=region.cds or [(region.start, region.end)],
    )


async def piga_inputs(
    site_id: str, strain_gene: str, reference_gene: str
) -> PseudogeneInputs | ToolErrorPayload:
    if strain_gene != NF54_PIGA:
        return tool_error("VALIDATION_ERROR", f"{strain_gene} names no gene")
    strain = load("pfalNF54_piga.json")
    return PseudogeneInputs(
        reference=reference_piga(),
        reference_models=ReadModels(
            models=[spans(reference_gene, load("pfal3D7_piga.json"))]
        ),
        strain_window=GenomeWindow(
            seqid=strain.seqid, start=strain.start, sequence=strain.sequence
        ),
        strand="-",
        gene_ids=[
            GeneId(given=strain_gene, resolved=NF54_PIGA_ID),
            GeneId(given=reference_gene, resolved=reference_gene),
        ],
    )


async def selk_inputs(
    site_id: str, gene: str, reference_gene: str
) -> SelenoproteinInputs | ToolErrorPayload:
    gt1 = load_protein("tgonGT1_selk.json")
    return SelenoproteinInputs(
        model_protein=gt1.model_protein,
        reference_protein=reference_protein("tgonME49_selk.json"),
        dna=gt1.sequence,
        strand="+",
        gene_ids=[
            GeneId(given=gene, resolved=gene),
            GeneId(given=reference_gene, resolved=reference_gene),
        ],
        models=ReadModels(
            models=[
                spans(gene, load("tgonGT1_selk.json")),
                spans(reference_gene, load("tgonME49_selk.json")),
            ]
        ),
    )
