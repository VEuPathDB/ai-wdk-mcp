from __future__ import annotations

import pytest
from tests._support.record_columns_site import serve_recorded_records


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    serve_recorded_records(monkeypatch)
