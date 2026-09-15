"""A literature API that answers 200 with a body that is not JSON is refusing.

The client names the service and asks once. A raw decode error would reach the
caller unnamed, after one wasted retry round per attempt.
"""

from __future__ import annotations

from types import TracebackType
from typing import ClassVar

import httpx
import pytest
from veupathdb.errors import ExternalServiceError

from veupathdb_mcp.research.literature.clients.crossref import CrossrefClient
from veupathdb_mcp.research.literature.clients.europepmc import EuropePmcClient
from veupathdb_mcp.research.literature.clients.openalex import OpenAlexClient
from veupathdb_mcp.research.literature.clients.pubmed import PubmedClient
from veupathdb_mcp.research.literature.clients.semanticscholar import (
    SemanticScholarClient,
)
from veupathdb_mcp.research.literature.search import LiteratureSearchService

HTML_BODY = "<html><head><title>502 Bad Gateway</title></head></html>"


class _HtmlClient:
    """Stands in for ``httpx.AsyncClient`` and answers 200 with an HTML page."""

    asked: ClassVar[list[str]] = []

    def __init__(self, *, timeout: float, headers: dict[str, str]) -> None:
        del timeout, headers

    async def __aenter__(self) -> "_HtmlClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False

    async def get(
        self,
        url: str,
        params: dict[str, str],
        follow_redirects: bool = False,
    ) -> httpx.Response:
        del params, follow_redirects
        _HtmlClient.asked.append(url)
        return httpx.Response(200, text=HTML_BODY, request=httpx.Request("GET", url))


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    _HtmlClient.asked = []
    monkeypatch.setattr(httpx, "AsyncClient", _HtmlClient)
    return _HtmlClient.asked


async def test_openalex_names_itself_and_asks_once(asked: list[str]) -> None:
    with pytest.raises(ExternalServiceError) as refused:
        await OpenAlexClient().search("kinase", limit=2, abstract_max_chars=200)

    assert "OpenAlex" in str(refused.value)
    assert len(asked) == 1


async def test_crossref_names_itself_and_asks_once(asked: list[str]) -> None:
    with pytest.raises(ExternalServiceError) as refused:
        await CrossrefClient().search("kinase", limit=2, abstract_max_chars=200)

    assert "CrossRef" in str(refused.value)
    assert len(asked) == 1


async def test_europepmc_names_itself_and_asks_once(asked: list[str]) -> None:
    with pytest.raises(ExternalServiceError) as refused:
        await EuropePmcClient().search("kinase", limit=2, abstract_max_chars=200)

    assert "EuropePMC" in str(refused.value)
    assert len(asked) == 1


async def test_semantic_scholar_names_itself_and_asks_once(asked: list[str]) -> None:
    with pytest.raises(ExternalServiceError) as refused:
        await SemanticScholarClient().search("kinase", limit=2, abstract_max_chars=200)

    assert "Semantic Scholar" in str(refused.value)
    assert len(asked) == 1


async def test_pubmed_names_itself_and_asks_once(asked: list[str]) -> None:
    with pytest.raises(ExternalServiceError) as refused:
        await PubmedClient().search(
            "kinase", limit=2, include_abstract=False, abstract_max_chars=200
        )

    assert "PubMed" in str(refused.value)
    assert len(asked) == 1


async def test_a_source_that_answers_html_is_named_in_the_sources_status(
    asked: list[str],
) -> None:
    resp = await LiteratureSearchService().search("kinase", source="openalex", limit=2)

    assert [(s.source, s.results) for s in resp.sources_status] == [("openalex", 0)]
    assert "OpenAlex" in (resp.sources_status[0].error or "")
    assert len(asked) == 1
