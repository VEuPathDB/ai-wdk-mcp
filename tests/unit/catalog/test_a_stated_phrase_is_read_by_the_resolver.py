"""A stated term names a vocabulary entry exactly, or is refused with the ranked candidates."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain.parameters import (
    MultiPickValue,
    SinglePickValue,
    VocabularyEntryError,
)
from veupathdb.testing import NEEDS_QA_RECORDING, needs_qa_recording
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog import ResolveContext, read_under_parents
from veupathdb_mcp.catalog.param_dag import ParamFetcher
from veupathdb_mcp.catalog.param_phyletic import (
    PhyleticUnresolvedProposal,
    derive_phyletic_overrides,
)

_TAXON = "search_genes_by_taxon"
_SNPS = "search_genes_by_ngs_snps"
_ORTHOLOGS = "search_genes_by_ortholog_pattern"
_SRC = Path(__file__).resolve().parents[3] / "src"

_ABOUT = ResolveContext(site_id="plasmodb")


def _declarations(fixture: str) -> list[WDKParameter]:
    search = WDKSearchResponse.model_validate(load_recorded(fixture).json_body())
    return search.search_data.parameters or []


def _serving(fixture: str) -> ParamFetcher:
    declarations = _declarations(fixture)

    async def fetch_at(context: dict[str, str]) -> list[WDKParameter]:
        del context
        return declarations

    return fetch_at


async def _refusal(fixture: str, stated: dict[str, JsonValue]) -> VocabularyEntryError:
    with pytest.raises(VocabularyEntryError) as refused:
        await read_under_parents(
            _serving(fixture), stated, FilterReadsDouble(), about=_ABOUT
        )
    return refused.value


@pytest.mark.skipif(needs_qa_recording(f"wdk/{_TAXON}.json"), reason=NEEDS_QA_RECORDING)
class TestAnOrganism:
    async def test_the_entry_as_spelled_binds(self) -> None:
        read = await read_under_parents(
            _serving(_TAXON),
            {"organism": ["plasmodium falciparum 3d7"]},
            FilterReadsDouble(),
            about=_ABOUT,
        )

        assert read["organism"] == MultiPickValue(values=["Plasmodium falciparum 3D7"])

    @pytest.mark.parametrize("phrase", ["P. falciparum 3D7", "Pf3D7"])
    async def test_a_phrase_no_entry_spells_is_refused_with_the_entry_first(
        self, phrase: str
    ) -> None:
        refused = await _refusal(_TAXON, {"organism": [phrase]})

        [(param, resolution)] = refused.faults
        assert param == "organism"
        assert resolution.phrase == phrase
        assert resolution.candidates[0].value == "Plasmodium falciparum 3D7"
        assert len(resolution.candidates) == 5

    async def test_two_unnamed_terms_of_one_statement_are_one_refusal(self) -> None:
        refused = await _refusal(_TAXON, {"organism": ["Pf3D7", "PbANKA"]})

        assert [(p, r.phrase) for p, r in refused.faults] == [
            ("organism", "Pf3D7"),
            ("organism", "PbANKA"),
        ]
        assert len(str(refused.detail).splitlines()) == 2


@pytest.mark.skipif(needs_qa_recording(f"wdk/{_SNPS}.json"), reason=NEEDS_QA_RECORDING)
class TestASnpClass:
    async def test_non_synonymous_is_refused_and_never_binds_synonymous(self) -> None:
        refused = await _refusal(_SNPS, {"snp_class": "non-synonymous"})

        [(param, resolution)] = refused.faults
        assert param == "snp_class"
        assert resolution.value is None
        assert "Synonymous" in [c.value for c in resolution.candidates]

    async def test_a_class_in_another_case_binds(self) -> None:
        read = await read_under_parents(
            _serving(_SNPS),
            {"snp_class": "missense"},
            FilterReadsDouble(),
            about=_ABOUT,
        )

        assert read["snp_class"] == SinglePickValue(value="Missense")


@pytest.mark.skipif(
    needs_qa_recording(f"wdk/{_ORTHOLOGS}.json"), reason=NEEDS_QA_RECORDING
)
def test_a_genus_the_species_lists_lack_names_its_genomes_first() -> None:
    got = derive_phyletic_overrides(
        _declarations(_ORTHOLOGS), {"included_species": "Plasmodium"}
    )

    assert isinstance(got, PhyleticUnresolvedProposal)
    nearest = [entry.value for entry in got.nearest]
    assert nearest[:3] == ["padl", "pbbi", "pber"]
    assert "Plasmodium vivax PAM" not in [entry.display for entry in got.nearest]


def test_no_reader_matches_a_vocabulary_value_of_its_own() -> None:
    held = [
        f"{path.relative_to(_SRC)}: {needle}"
        for path in _SRC.rglob("*.py")
        for needle in ("nearest_entries", "vocab_lookup import", "pick_vocab_entry")
        if needle in path.read_text()
    ]

    assert held == []
