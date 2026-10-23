import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from pydantic import JsonValue
from scripts.record_audit_gene_ids import (
    BESIDE,
    FILE,
    GIVEN,
    SITE,
    GeneIdRecording,
)
from tests._support.row_reads import serve_recorded_rows
from tests._support.wdk_genes import (
    FIXTURES,
    Datasets,
    ReportSite,
    answer_of,
    gene_attributes,
    record,
)
from veupathdb import JSONObject
from veupathdb.errors import DataParsingError
from veupathdb.wdk import WDKAnswer, WDKSearchConfig, WDKSearchResponse

from veupathdb_mcp.audit import gene_ids, genes, served
from veupathdb_mcp.audit.gene_ids import (
    ID_FIELDS,
    MAX_MATCHES,
    TEXT_ORGANISMS,
    TEXT_SEARCH,
    GeneId,
    GeneIdProblem,
    GeneIdRefusal,
    id_pairs,
)
from veupathdb_mcp.tools.refusals import payload_or_error
from veupathdb_mcp.wdk.site_cache import SiteCache

RESOLVED = "PfNF54_100037200:pseudogene"
IT_PSEUDOGENE = "PfIT_100037300:pseudogene"


def recorded() -> GeneIdRecording:
    return GeneIdRecording.model_validate_json((FIXTURES / FILE).read_text())


def answers(bodies: list[JsonValue]) -> list[WDKAnswer]:
    return [WDKAnswer.model_validate(body) for body in bodies]


class TextSite:
    def __init__(self, search: WDKSearchResponse, text: list[WDKAnswer]) -> None:
        self.search = search
        self.text = text
        self.details: list[tuple[str, str]] = []
        self.searches: list[tuple[str, str, WDKSearchConfig, JSONObject | None]] = []

    async def get_search_details(
        self, record_type: str, search_name: str
    ) -> WDKSearchResponse:
        self.details.append((record_type, search_name))
        return self.search

    async def run_search_report(
        self,
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        self.searches.append((record_type, search_name, search_config, report_config))
        return self.text[len(self.searches) - 1]


def serve(
    monkeypatch: pytest.MonkeyPatch, locus: list[WDKAnswer], text: list[WDKAnswer]
) -> tuple[ReportSite, TextSite]:
    private = ReportSite(locus)
    site = TextSite(WDKSearchResponse.model_validate(recorded().search), text)

    @asynccontextmanager
    async def opened(site_id: str) -> AsyncIterator[ReportSite]:
        yield private

    monkeypatch.setattr(genes, "dataset_client", opened)
    monkeypatch.setattr(genes, "StrategyAPI", Datasets)
    monkeypatch.setattr(gene_ids, "get_wdk_client", lambda site_id: site)
    monkeypatch.setattr(gene_ids, "_ORGANISMS", SiteCache())
    return private, site


def echoed(gene: str, transcript: str, inputs: str, pseudo: str = "No") -> JSONObject:
    kind = "pseudogene" if pseudo == "Yes" else "protein coding gene"
    attributes: JSONObject = {**gene_attributes("", pseudo, kind), "input_id": inputs}
    return record(gene, transcript, attributes)


async def test_a_plain_nf54_id_beside_piga_resolves_through_the_text_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = recorded()
    locus, text = serve(monkeypatch, [], answers(wire.text))
    reads = serve_recorded_rows(monkeypatch, [*wire.batch, *wire.resolved])

    rows = payload_or_error(await served.located(SITE, [GIVEN, BESIDE]))

    assert {given: row.gene for given, row in rows.items()} == {
        GIVEN: RESOLVED,
        BESIDE: BESIDE,
    }
    assert (rows[GIVEN].pseudo, rows[GIVEN].organism) == (
        True,
        "Plasmodium falciparum NF54",
    )
    assert reads.reads == [GIVEN, RESOLVED, BESIDE]
    assert (locus.datasets, locus.searches) == ([], [])
    assert text.details == [("transcript", TEXT_SEARCH)]
    [(record_type, search_name, config, report)] = text.searches
    assert (record_type, search_name) == ("transcript", TEXT_SEARCH)
    assert config.parameters["text_expression"] == GIVEN
    assert json.loads(config.parameters["text_fields"]) == list(ID_FIELDS)
    organisms = json.loads(config.parameters[TEXT_ORGANISMS])
    assert (len(organisms), "Plasmodium falciparum NF54" in organisms) == (63, True)
    assert report == {
        "attributes": [],
        "tables": [],
        "pagination": {"offset": 0, "numRecords": MAX_MATCHES},
    }
    assert id_pairs([GIVEN, BESIDE], rows) == [
        GeneId(given=GIVEN, resolved=RESOLVED),
        GeneId(given=BESIDE, resolved=BESIDE),
    ]


def test_the_recording_holds_the_nf54_id_matched_by_text() -> None:
    wire = recorded()
    [text] = answers(wire.text)

    assert (wire.site, wire.given, BESIDE) == (
        "plasmodb",
        "PfNF54_100037200",
        "PF3D7_1032400",
    )
    assert gene_ids.matched_genes(text, GIVEN) == [RESOLVED]


def test_a_text_match_on_a_transcript_id_names_its_gene() -> None:
    hit = echoed(BESIDE, f"{BESIDE}.1", "-")

    assert gene_ids.matched_genes(answer_of([hit]), f"{BESIDE}.1") == [BESIDE]
    assert gene_ids.matched_genes(answer_of([hit]), f"{BESIDE}.2") == []


async def test_rows_and_proteins_are_read_by_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locus, _ = serve(monkeypatch, [], [])
    served_rows = [
        record(
            BESIDE, BESIDE + ".1", gene_attributes("461", "No", "protein coding gene")
        )
    ]
    reads_made = serve_recorded_rows(monkeypatch, [answer_body(served_rows)])
    reads_made.proteins[BESIDE] = "MKVLL"

    reads = payload_or_error(await gene_ids.rows_and_proteins(SITE, [BESIDE]))

    assert [row.gene for row in reads.rows] == [BESIDE]
    assert (reads.proteins, reads.inputs) == (
        {BESIDE: "MKVLL"},
        {"pf3d7_1032400": [BESIDE]},
    )
    assert (reads_made.reads, reads_made.protein_reads) == ([BESIDE], [BESIDE])
    assert locus.datasets == []


@pytest.mark.parametrize("given", ["PF3D7_10*", "PF3D7 1032400"])
async def test_an_id_with_a_wildcard_or_a_space_is_not_searched_as_text(
    monkeypatch: pytest.MonkeyPatch, given: str
) -> None:
    _, text = serve(monkeypatch, [], [])

    refused = await gene_ids.genes_by_text(SITE, given)

    assert refused == GeneIdRefusal(
        given=given,
        problem=GeneIdProblem.NOT_AN_ID,
        message=f"{given} holds a wildcard or a space; a gene id holds neither",
    )

    assert (text.details, text.searches) == ([], [])


async def test_a_text_answer_over_the_limit_is_refused_naming_the_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [text] = answers(recorded().text)
    over = text.model_copy(
        update={"meta": text.meta.model_copy(update={"total_count": 51})}
    )
    locus, _ = serve(monkeypatch, [], [over])

    refused = await gene_ids.genes_by_text(SITE, GIVEN)

    assert refused == GeneIdRefusal(
        given=GIVEN,
        problem=GeneIdProblem.TOO_MANY_MATCHES,
        message=f"{GIVEN} matches more than 50 transcripts of {SITE}",
    )

    assert locus.searches == []


async def test_a_text_match_on_another_genes_id_is_not_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locus, _ = serve(monkeypatch, [], answers(recorded().text))

    assert await gene_ids.genes_by_text(SITE, "PF10_0327") == []
    assert locus.searches == []


async def test_two_genes_a_text_match_names_are_refused_before_any_row_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    both = answer_of([echoed("X1", "X1.1", "-"), echoed("X1:pseudogene", "X1.2", "-")])
    locus, _ = serve(monkeypatch, [], [both])

    refused = await gene_ids.genes_by_text(SITE, "X1")

    assert refused == GeneIdRefusal(
        given="X1",
        problem=GeneIdProblem.SEVERAL_GENES,
        message="X1 names 2 genes of plasmodb: X1, X1:pseudogene",
    )

    assert locus.searches == []


async def test_the_organism_tree_is_read_once_per_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, text = serve(monkeypatch, [], [])

    first = await gene_ids.text_organisms(SITE)
    second = await gene_ids.text_organisms(SITE)

    assert first == second
    assert len(first) == 63
    assert text.details == [("transcript", TEXT_SEARCH)]


async def test_a_text_search_without_an_organism_tree_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, text = serve(monkeypatch, [], [])
    params = [
        p for p in text.search.search_data.parameters or [] if p.name != TEXT_ORGANISMS
    ]
    data = text.search.search_data.model_copy(update={"parameters": params})
    text.search = text.search.model_copy(update={"search_data": data})

    with pytest.raises(DataParsingError, match=f"lists no {TEXT_ORGANISMS} tree"):
        await gene_ids.text_organisms(SITE)


async def test_an_id_in_many_aliases_still_names_its_own_suffixed_gene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    own = echoed(RESOLVED, "PfNF54_100037200.1", "-", pseudo="Yes")
    aliased = [echoed(f"PF3D7_{n:07d}", f"PF3D7_{n:07d}.1", "-") for n in range(60)]
    wire = recorded()
    locus, text = serve(monkeypatch, [], [])
    reads_made = serve_recorded_rows(monkeypatch, wire.resolved)

    async def by_fields(
        record_type: str,
        search_name: str,
        search_config: WDKSearchConfig,
        report_config: JSONObject | None = None,
    ) -> WDKAnswer:
        text.searches.append((record_type, search_name, search_config, report_config))
        fields = json.loads(search_config.parameters["text_fields"])
        matched = [own, *(aliased if "Alias" in fields else [])]
        shown = matched[:MAX_MATCHES]
        return answer_of(shown, total=len(matched))

    monkeypatch.setattr(text, "run_search_report", by_fields)

    found = payload_or_error(await gene_ids.genes_by_text(SITE, GIVEN))

    assert [row.gene for row in found] == [RESOLVED]
    assert (reads_made.reads, locus.datasets) == ([RESOLVED], [])


def answer_body(records: list[JSONObject]) -> JSONObject:
    return answer_of(records).model_dump(mode="json", by_alias=True)
