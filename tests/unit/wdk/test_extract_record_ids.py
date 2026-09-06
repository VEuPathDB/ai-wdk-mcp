"""Reading an id out of a record attribute.

The attribute may be a link object, so the value a reader sees is the display
text rather than the whole object.
"""

from __future__ import annotations

from typing import Any

from veupathdb.wdk.wdk_models import WDKRecordInstance

from veupathdb_mcp.wdk.helpers import extract_record_ids


def _record(attributes: dict[str, Any], pk: str = "PF3D7_0100100") -> WDKRecordInstance:
    return WDKRecordInstance.model_validate(
        {
            "id": [{"name": "source_id", "value": pk}],
            "attributes": attributes,
        }
    )


class TestThePreferredKey:
    def test_a_plain_attribute_is_used(self) -> None:
        records = [_record({"gene_source_id": "PF3D7_0200100"})]

        assert extract_record_ids(records, preferred_key="gene_source_id") == [
            "PF3D7_0200100"
        ]

    def test_a_link_attribute_is_used_by_its_display_text(self) -> None:
        records = [
            _record(
                {
                    "gene_source_id": {
                        "url": "/a/app/record/gene/PF3D7_0200100",
                        "displayText": "PF3D7_0200100",
                    }
                }
            )
        ]

        assert extract_record_ids(records, preferred_key="gene_source_id") == [
            "PF3D7_0200100"
        ]

    def test_surrounding_space_is_trimmed(self) -> None:
        records = [_record({"gene_source_id": "  PF3D7_0200100  "})]

        assert extract_record_ids(records, preferred_key="gene_source_id") == [
            "PF3D7_0200100"
        ]


class TestThePrimaryKeyIsTheFallback:
    def test_an_absent_attribute_falls_back(self) -> None:
        records = [_record({})]

        assert extract_record_ids(records, preferred_key="gene_source_id") == [
            "PF3D7_0100100"
        ]

    def test_a_null_attribute_falls_back(self) -> None:
        records = [_record({"gene_source_id": None})]

        assert extract_record_ids(records, preferred_key="gene_source_id") == [
            "PF3D7_0100100"
        ]

    def test_no_preferred_key_uses_the_primary_key(self) -> None:
        records = [_record({"gene_source_id": "PF3D7_0200100"})]

        assert extract_record_ids(records) == ["PF3D7_0100100"]

    def test_a_record_with_neither_is_dropped(self) -> None:
        records = [WDKRecordInstance.model_validate({"attributes": {}})]

        assert extract_record_ids(records, preferred_key="gene_source_id") == []
