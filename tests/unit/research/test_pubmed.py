"""The PubMed esummary answer carries a uid list beside its article entries."""

from __future__ import annotations

from types import TracebackType
from typing import ClassVar

import httpx
import pytest
from pydantic import JsonValue
from veupathdb.errors import ExternalServiceError

from veupathdb_mcp.research.literature.clients import pubmed
from veupathdb_mcp.research.literature.clients.pubmed import PubmedClient
from veupathdb_mcp.research.settings import ResearchSettings

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


class _RecordingClient(_StubClient):
    sent: ClassVar[list[dict[str, str]]] = []

    async def get(self, url: str, params: dict[str, str]) -> _StubResponse:
        _RecordingClient.sent.append(params)
        return await super().get(url, params)


async def _sent_params(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> list[dict[str, str]]:
    _RecordingClient.sent = []
    monkeypatch.setattr(pubmed.httpx, "AsyncClient", _RecordingClient)
    monkeypatch.setattr(
        pubmed, "get_research_settings", lambda: ResearchSettings(ncbi_api_key=key)
    )
    await PubmedClient().search(
        "kinase", limit=2, include_abstract=False, abstract_max_chars=200
    )
    return _RecordingClient.sent


async def test_every_ncbi_call_carries_the_configured_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = await _sent_params(monkeypatch, "ncbi-key")

    assert [params.get("api_key") for params in sent] == ["ncbi-key", "ncbi-key"]


async def test_no_key_sends_no_key_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = await _sent_params(monkeypatch, "")

    assert [sorted(params) for params in sent] == [
        ["db", "retmax", "retmode", "term"],
        ["db", "id", "retmode"],
    ]


class _RefusingClient(_StubClient):
    async def get(self, url: str, params: dict[str, str]) -> _StubResponse:
        request = httpx.Request("GET", url, params=params)
        httpx.Response(500, request=request).raise_for_status()
        return _StubResponse({})


async def test_a_failed_call_never_names_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pubmed.httpx, "AsyncClient", _RefusingClient)
    monkeypatch.setattr(
        pubmed,
        "get_research_settings",
        lambda: ResearchSettings(ncbi_api_key="secret-ncbi-key"),
    )

    with pytest.raises(ExternalServiceError) as refused:
        await PubmedClient().search(
            "kinase", limit=2, include_abstract=False, abstract_max_chars=200
        )

    assert "secret-ncbi-key" not in str(refused.value)
    assert "api_key=***" in str(refused.value)
