import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, JsonValue
from veupathdb.domain.parameters import VocabOption
from veupathdb.wdk import WDKSearch, WDKSearchResponse

from veupathdb_mcp.catalog.decisions import (
    DECISIONS_URL,
    DecisionRequest,
    DecisionResponse,
)
from veupathdb_mcp.catalog.search_picks import catalog_choice_request
from veupathdb_mcp.catalog.vocab_lookup import read_options
from veupathdb_mcp.catalog.vocab_pick import NONE_FITS, choice_request, fit_request
from veupathdb_mcp.catalog.vocab_rendering import entries_of

FIXTURES = Path(__file__).resolve().parent.parent / "tests/unit/catalog/fixtures"
SITE = "plasmodb"
CATALOG_QUERY = "Plasmodium falciparum 3D7 genes with a protein kinase domain"
VOCAB_TERM = "protein kinase"
VOCAB_PARAM = "domain_typeahead"
OFFERED = [
    WDKSearch(url_segment=name, display_name=display, description=description)
    for name, display, description in (
        (
            "GenesByText",
            "Text (product name, notes, etc.)",
            "Find genes whose annotation text holds a word or phrase.",
        ),
        ("GenesByGoTerm", "GO Term", "Find genes annotated with a Gene Ontology term."),
        (
            "GenesByInterproDomain",
            "InterPro Domain",
            "Find genes whose proteins hold a domain from InterPro or its member databases.",
        ),
        (
            "GenesByEcNumber",
            "EC Number",
            "Find genes by the Enzyme Commission number of their product.",
        ),
        (
            "GenesByMolecularWeight",
            "Molecular Weight",
            "Find genes by the predicted molecular weight of their protein.",
        ),
        (
            "GenesByExportPrediction",
            "Exported Protein",
            "Find genes whose proteins carry a PEXEL export motif.",
        ),
        (
            "GenesBySignalPeptide",
            "Signal Peptide",
            "Find genes whose proteins are predicted to carry a signal peptide.",
        ),
        (
            "GenesByTransmembraneDomains",
            "Transmembrane Domain Count",
            "Find genes by the predicted number of transmembrane domains.",
        ),
        ("GenesByLocation", "Genomic Location", "Find genes in a chromosome region."),
        (
            "GenesByOrthologPattern",
            "Orthology Phylogenetic Profile",
            "Find genes by the species their ortholog group holds or lacks.",
        ),
    )
]
INTERPRO = "plasmodb_3d7_interpro_vocabulary_half_off.json"


class Exchange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: DecisionRequest
    response: JsonValue


class DecisionsWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str
    query: str
    exchanges: list[Exchange]


def interpro_parameter() -> tuple[str, list[VocabOption]]:
    recorded = json.loads((FIXTURES / INTERPRO).read_text())["response_json"]
    params = WDKSearchResponse.model_validate(recorded).search_data.parameters or []
    param = next(p for p in params if p.name == VOCAB_PARAM)
    kept = read_options(entries_of(param.vocabulary), [VOCAB_TERM], request_terms=[])
    return param.display_name or param.name, kept.options


async def _ask(client: httpx.AsyncClient, request: DecisionRequest) -> Exchange:
    response = await client.post(DECISIONS_URL, json=request.model_dump(mode="json"))
    response.raise_for_status()
    return Exchange(request=request, response=response.json())


async def record(into: Path) -> None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        msg = "OPENAI_API_KEY is not set"
        raise RuntimeError(msg)
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        catalog = catalog_choice_request(SITE, ["transcript"], CATALOG_QUERY, OFFERED)
        if catalog is None:
            msg = "the listing offers fewer than two searches"
            raise RuntimeError(msg)
        wire = DecisionsWire(
            site=SITE, query=CATALOG_QUERY, exchanges=[await _ask(client, catalog)]
        )
        (into / "decisions_plasmodb_catalog_choice.json").write_text(
            wire.model_dump_json(indent=1) + "\n"
        )
        display, entries = interpro_parameter()
        chosen = await _ask(client, choice_request(SITE, display, VOCAB_TERM, entries))
        exchanges = [chosen]
        answer = DecisionResponse.model_validate(chosen.response).choice("value")
        if answer is not None and answer.choice != NONE_FITS:
            entry = entries[int(answer.choice.removeprefix("e"))]
            exchanges.append(
                await _ask(client, fit_request(SITE, display, VOCAB_TERM, entry))
            )
        (into / "decisions_plasmodb_interpro_pick.json").write_text(
            DecisionsWire(
                site=SITE, query=VOCAB_TERM, exchanges=exchanges
            ).model_dump_json(indent=1)
            + "\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    asyncio.run(record(parser.parse_args().out))
