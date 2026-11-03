from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from veupathdb.wdk import WDKAnswer, WDKRecordInstance, WDKSearchResponse

from veupathdb_mcp.audit.frameshift_inputs import variant_record

_FIXTURE = (
    Path(__file__).parent.parent
    / "unit"
    / "audit"
    / "fixtures"
    / "plasmodb_variants_by_location.json"
)


class RecordedAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    indel: WDKRecordInstance
    snv: WDKRecordInstance


class VariantWire(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    details: WDKSearchResponse
    search: WDKAnswer
    refused_status: int = Field(validation_alias="refusedStatus")
    snv: WDKRecordInstance
    indel: WDKRecordInstance
    attributes: RecordedAttributes


WIRE = VariantWire.model_validate_json(_FIXTURE.read_text())
SNV_ID = "Variant_Pf3D7_04_v3_514183"
INDEL_ID = "Variant_Pf3D7_01_v3_283234"


def joined(
    tables: WDKRecordInstance, attributes: WDKRecordInstance
) -> WDKRecordInstance:
    return tables.model_copy(update={"attributes": attributes.attributes})


SERVED_SNV = joined(WIRE.snv, WIRE.attributes.snv)
SERVED_INDEL = joined(WIRE.indel, WIRE.attributes.indel)
SNV = variant_record(SERVED_SNV)
INDEL = variant_record(SERVED_INDEL)
