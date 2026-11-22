"""A stated organism names a site entry and restricts the lookup; one the query implies never removes a record."""

from __future__ import annotations

import pytest
from veupathdb.domain.parameters import VocabularyEntryError

from veupathdb_mcp.catalog import (
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
    ResolveContext,
    use_decisions_transport,
)
from veupathdb_mcp.gene_lookup import lookup
from veupathdb_mcp.gene_lookup.lookup import lookup_genes_by_text
from veupathdb_mcp.gene_lookup.result import GeneResult
from veupathdb_mcp.gene_lookup.wdk import WdkTextResult

_FALCIPARUM = "Plasmodium falciparum 3D7"
_VIVAX = "Plasmodium vivax P01"
_PAGE = [
    GeneResult(
        gene_id=f"{prefix}_{i:04d}",
        display_name="kinase",
        organism=org,
        product="kinase",
    )
    for prefix, org in (("PF3D7", _FALCIPARUM), ("PVP01", _VIVAX))
    for i in range(3)
]


class _Site:
    def __init__(self) -> None:
        self.searched: list[list[str] | None] = []

    async def page(
        self,
        site_id: str,
        search_text: str,
        *,
        organisms: list[str] | None = None,
        limit: int = 50,
    ) -> tuple[list[GeneResult], list[str], int]:
        del site_id, search_text, limit
        self.searched.append(organisms)
        held = [r for r in _PAGE if organisms is None or r.organism in organisms]
        return held, sorted({r.organism for r in held}), len(held)


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> _Site:
    served = _Site()

    async def declared(site_id: str) -> list[str]:
        del site_id
        return [_FALCIPARUM, _VIVAX, "Plasmodium berghei ANKA"]

    async def no_wdk_text(*args: object, **kwargs: object) -> WdkTextResult:
        del args, kwargs
        return WdkTextResult(records=[], total_count=0)

    async def as_read(site_id: str, results: list[GeneResult]) -> list[GeneResult]:
        del site_id
        return results

    monkeypatch.setattr(lookup, "list_organisms", declared)
    monkeypatch.setattr(lookup, "fetch_site_search_genes", served.page)
    monkeypatch.setattr(lookup, "fetch_wdk_text_genes", no_wdk_text)
    monkeypatch.setattr(lookup, "hydrate_sparse_gene_results", as_read)
    return served


async def test_an_organism_the_query_implies_never_removes_a_record(
    site: _Site,
) -> None:
    result = await lookup_genes_by_text("plasmodb", _VIVAX, limit=20, about=None)

    assert {r.gene_id for r in result.records} == {r.gene_id for r in _PAGE}
    assert result.implied_organism == _VIVAX


async def test_a_stated_organism_in_another_case_restricts_to_its_entry(
    site: _Site,
) -> None:
    result = await lookup_genes_by_text(
        "plasmodb",
        "kinase",
        organism="plasmodium  falciparum 3d7",
        limit=20,
        about=None,
    )

    assert {r.organism for r in result.records} == {_FALCIPARUM}
    assert [_FALCIPARUM] in site.searched
    assert result.implied_organism is None


async def test_a_stated_organism_that_names_no_entry_is_refused_with_candidates(
    site: _Site,
) -> None:
    with pytest.raises(VocabularyEntryError) as refused:
        await lookup_genes_by_text(
            "plasmodb", "kinase", organism="Pf3D7", limit=20, about=None
        )

    [(param, resolution)] = refused.value.faults
    assert (param, resolution.phrase) == ("organism", "Pf3D7")
    assert resolution.candidates[0].value == _FALCIPARUM
    assert site.searched == []


async def test_a_refused_organism_leads_with_the_entry_a_choice_picks(
    site: _Site,
) -> None:
    picked: list[str] = []
    seen: list[DecisionRequest] = []

    async def picks_the_last(request: DecisionRequest) -> DecisionResponse:
        [question] = request.questions
        assert isinstance(question, ChoiceQuestion)
        last = question.choices[-2].value
        picked.append(question.choices[-2].description)
        seen.append(request)
        return DecisionResponse.model_validate(
            {
                "answers": [
                    {
                        "type": "choice",
                        "name": question.name,
                        "choice": last,
                        "probabilities": [{"value": last, "probability": 1.0}],
                        "confidence": 1.0,
                    }
                ]
            }
        )

    use_decisions_transport(picks_the_last)
    with pytest.raises(VocabularyEntryError) as refused:
        await lookup_genes_by_text(
            "plasmodb",
            "kinase",
            organism="Pb",
            limit=20,
            about=ResolveContext(site_id="plasmodb", message="Pb kinases"),
        )

    assert "The researcher's message: Pb kinases" in seen[0].input
    [(_, resolution)] = refused.value.faults
    assert resolution.how == "unsettled"
    assert resolution.candidates[0].value == picked[0]
    assert picked[0] != "Plasmodium berghei ANKA"
    assert site.searched == []
