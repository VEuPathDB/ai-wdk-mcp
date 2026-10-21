import json
from pathlib import Path

from pydantic import JsonValue
from scripts.record_audit_evidence import served_tables, write_bodies


def test_a_recorded_record_type_keeps_its_key_columns_and_tables_as_served() -> None:
    tables: JsonValue = [
        {"name": "PdbSimilarities", "attributes": [{"name": "pdb_id"}]},
        {"name": "Notes", "displayName": "Notes from Annotator"},
    ]
    keys: JsonValue = ["source_id", "project_id"]
    served: JsonValue = {
        "urlSegment": "gene",
        "primaryKeyColumnRefs": keys,
        "tables": tables,
    }

    assert served_tables(served) == {"primaryKeyColumnRefs": keys, "tables": tables}


def test_recorded_bodies_are_written_as_served(tmp_path: Path) -> None:
    record: JsonValue = {"id": [], "tables": {"Notes": [{"comment_string": "x"}]}}
    write_bodies(tmp_path, {"r.json": record})

    assert json.loads((tmp_path / "r.json").read_text()) == record
