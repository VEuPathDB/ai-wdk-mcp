"""The PubMed esummary answer carries a uid list beside its article entries."""

from __future__ import annotations

from types import TracebackType

import pytest
from pydantic import JsonValue

from veupathdb_mcp.research.literature.clients import pubmed
from veupathdb_mcp.research.literature.clients.pubmed import PubmedClient

_ESEARCH = {"esearchresult": {"idlist": ["31234567", "31234568"]}}
_ESUMMARY: JsonValue = {
    "result": {
        "uids": ["31234567", "31234568"],
        "31234567": {
            "title": "A plant-like kinase in Plasmodium falciparum",
            "pubdate": "2010 Jul",
            "fulljournalname": "Science",
            "authors": [{"name": "Dvorin JD"}],
        },
        "31234568": "the entry NCBI could not build",
    }
}


class _StubResponse:
    def __init__(self, payload: JsonValue) -> None:
        self._payload = payload
        self.text = ""

    def raise_for_status(self) -> None:
        return

    def json(self) -> JsonValue:
        return self._payload


class _StubClient:
    def __init__(self, *, timeout: float, headers: dict[str, str]) -> None:
        del timeout, headers

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False

    async def get(self, url: str, params: dict[str, str]) -> _StubResponse:
        del params
        return _StubResponse(_ESEARCH if "esearch" in url else _ESUMMARY)


async def test_an_entry_that_is_not_an_article_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pubmed.httpx, "AsyncClient", _StubClient)

    response = await PubmedClient().search(
        "kinase", limit=2, include_abstract=False, abstract_max_chars=200
    )

    assert [paper.pmid for paper in response.results] == ["31234567"]
    assert response.results[0].journal_title == "Science"
