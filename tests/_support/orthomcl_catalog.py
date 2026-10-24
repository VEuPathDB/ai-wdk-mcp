from __future__ import annotations

from pathlib import Path

from pydantic import JsonValue
from veupathdb.testing.wdk_fixtures import RecordedWDKResponse, load_recorded
from veupathdb.wdk import WDKAttributeField, WDKRecordType, WDKSearch, WDKSearchResponse

FIXTURES = Path(__file__).parent.parent / "unit" / "wdk" / "fixtures"


def recorded_body(name: str) -> JsonValue:
    recorded = RecordedWDKResponse.model_validate_json(
        (FIXTURES / f"{name}.json").read_text()
    )
    return recorded.json_body()


def orthomcl_group() -> WDKRecordType:
    return WDKRecordType.model_validate(recorded_body("orthomcl_group_record_type"))


def orthomcl_sequence() -> WDKRecordType:
    return WDKRecordType.model_validate(recorded_body("orthomcl_sequence_record_type"))


def orthomcl_record_types() -> list[WDKRecordType]:
    return [orthomcl_group(), orthomcl_sequence()]


def genes_by_orthologs() -> WDKSearch:
    body = load_recorded("search_genes_by_orthologs").json_body()
    return WDKSearchResponse.model_validate(body).search_data


def build_attributes() -> list[WDKAttributeField]:
    body = load_recorded("record_type_build").json_body()
    return WDKRecordType.model_validate(body).attributes or []
