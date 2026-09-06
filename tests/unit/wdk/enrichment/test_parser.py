"""Enrichment parser: transform real WDK plugin responses (all-string,
camelCase rows under ``resultData``) into typed ``EnrichmentTerm``s.

Column names come from the step-analysis plugins in VEuPathDB/ApiCommonWebsite
(``Model/src/main/java/org/apidb/apicommon/model/stepanalysis``), not from WDK,
which passes plugin JSON through untouched. Confirmed against live PlasmoDB and
ToxoDB responses. See docs/knowledge/wdk/rules/searches-and-answers.md WDK-ANS-007.
"""

from __future__ import annotations

import pytest
from veupathdb.json_types import JSONObject

from veupathdb_mcp.wdk.enrichment.html import parse_result_genes_html
from veupathdb_mcp.wdk.enrichment.parser import (
    parse_enrichment_response,
    parse_enrichment_terms,
)


def _go_row() -> JSONObject:
    return {
        "goId": "GO:0004672",
        "goTerm": "protein kinase activity",
        "bgdGenes": "120",
        "resultGenes": (
            "<a href='?param.ds_gene_ids.idList="
            "PF3D7_0100100,PF3D7_0200200,PF3D7_0300300&autoRun=1'>3</a>"
        ),
        "percentInResult": "12.5",
        "foldEnrich": "3.48",
        "oddsRatio": "4.12",
        "pValue": "0.0001",
        "benjamini": "0.002",
        "bonferroni": "0.005",
    }


def test_parse_go_rows_yields_real_terms() -> None:
    [term] = parse_enrichment_terms([_go_row()], "go_function")
    assert term.term_id == "GO:0004672"
    assert term.term_name == "protein kinase activity"
    assert term.gene_count == 3
    assert term.genes == ["PF3D7_0100100", "PF3D7_0200200", "PF3D7_0300300"]
    assert term.background_count == 120
    assert term.fold_enrichment == pytest.approx(3.48)
    assert term.odds_ratio == pytest.approx(4.12)
    assert term.p_value == pytest.approx(0.0001)
    assert term.fdr == pytest.approx(0.002)
    assert term.bonferroni == pytest.approx(0.005)


def test_parse_pathway_rows_uses_pathway_id_and_name() -> None:
    row: JSONObject = {
        "pathwayId": "kegg_pfa00010",
        "pathwayName": "Glycolysis / Gluconeogenesis",
        "bgdGenes": "60",
        "resultGenes": "<a href='?param.ds_gene_ids.idList=PF3D7_0915000&autoRun=1'>1</a>",
        "foldEnrich": "2.10",
        "oddsRatio": "2.5",
        "pValue": "0.01",
        "benjamini": "0.04",
        "bonferroni": "0.09",
    }
    [term] = parse_enrichment_terms([row], "pathway")
    assert term.term_id == "kegg_pfa00010"
    assert term.term_name == "Glycolysis / Gluconeogenesis"
    assert term.gene_count == 1
    assert term.genes == ["PF3D7_0915000"]
    assert term.p_value == pytest.approx(0.01)


def test_word_rows_map_word_to_id_and_pathway_name_to_description() -> None:
    # WordEnrichmentPlugin.ResultRow.toJson writes json.put("pathwayName", _descrip),
    # so the word plugin's description column arrives under the pathway plugin's key.
    row: JSONObject = {
        "word": "kinase",
        "pathwayName": "protein kinase, putative",
        "bgdGenes": "200",
        "resultGenes": "42",
        "foldEnrich": "1.8",
        "pValue": "0.005",
        "benjamini": "0.02",
        "bonferroni": "0.06",
    }
    [term] = parse_enrichment_terms([row], "word")
    assert term.term_id == "kinase"
    assert term.term_name == "protein kinase, putative"
    # Plain-count resultGenes (no HTML link) → count, no IDs.
    assert term.gene_count == 42
    assert term.genes == []


def test_result_genes_html_extracts_count_and_ids() -> None:
    count, genes = parse_result_genes_html(
        "<a href='?param.ds_gene_ids.idList=PF3D7_0100100,PF3D7_0200200&autoRun=1'>2</a>"
    )
    assert count == 2
    assert genes == ["PF3D7_0100100", "PF3D7_0200200"]


def test_malformed_row_missing_go_id_is_skipped() -> None:
    rows: list[JSONObject] = [{"goTerm": "no id here", "pValue": "0.1"}, _go_row()]
    terms = parse_enrichment_terms(rows, "go_process")
    # Only the well-formed row survives.
    assert [t.term_id for t in terms] == ["GO:0004672"]


def test_infinity_becomes_none_not_a_finite_number() -> None:
    row: JSONObject = {**_go_row(), "pValue": "Infinity", "foldEnrich": "Infinity"}
    [term] = parse_enrichment_terms([row], "go_process")
    assert term.p_value is None
    assert term.fold_enrichment is None
    assert term.odds_ratio == pytest.approx(4.12)


def test_non_dict_result_yields_empty_envelope() -> None:
    assert parse_enrichment_response("not a dict").result_data == []
    assert parse_enrichment_response(None).result_data == []
