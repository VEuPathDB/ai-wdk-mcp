from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from tests._support.proteins import back_translate

from veupathdb_mcp.audit.codes import GeneticCode, translate

_FIXTURE = (
    Path(__file__).parent.parent
    / "unit"
    / "audit"
    / "fixtures"
    / "pfalNF54_poly_a_frameshift.json"
)
_RUN_LEFT = "GAATGG"
_REGION_RESIDUES = "KEYKKYKKNG"


class Nf54Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    strain_protein: str = Field(validation_alias="strainProtein")
    reference_protein: str = Field(validation_alias="referenceProtein")
    strain_region: str = Field(validation_alias="strainRegion")
    reference_region: str = Field(validation_alias="referenceRegion")


WIRE = Nf54Wire.model_validate_json(_FIXTURE.read_text())
MODEL_PROTEIN = WIRE.strain_protein
REFERENCE_PROTEIN = WIRE.reference_protein


def reference_coding() -> str:
    start = REFERENCE_PROTEIN.index(_REGION_RESIDUES)
    residues = (len(WIRE.reference_region) - 1) // 3
    dna = (
        back_translate(REFERENCE_PROTEIN[:start])
        + WIRE.reference_region[1 : 1 + 3 * residues]
        + back_translate(REFERENCE_PROTEIN[start + residues :])
    )
    assert translate(dna, GeneticCode.STANDARD) == REFERENCE_PROTEIN
    return dna


def run_offset(dna: str) -> int:
    return dna.index(_RUN_LEFT + "AAAA") + len(_RUN_LEFT)


def model_coding() -> str:
    dna = reference_coding()
    at = run_offset(dna)
    edited = dna[:at] + "A" + dna[at:]
    assert WIRE.strain_region[1:] in edited
    return edited
