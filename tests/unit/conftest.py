import pytest
from tests._support.record_types import RecordedRecordTypes, serve_record_types


@pytest.fixture(autouse=True)
def listed_record_types(monkeypatch: pytest.MonkeyPatch) -> RecordedRecordTypes:
    return serve_record_types(monkeypatch)
