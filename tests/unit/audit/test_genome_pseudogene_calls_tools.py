import json
import re
import threading
from collections import Counter

import httpx
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from tests._support.wdk_genes import FIXTURES, PF3D7, serve
from veupathdb.errors import WDKError
from veupathdb.wdk import WDKAnswer

from veupathdb_mcp.audit import pseudogene_calls_inputs
from veupathdb_mcp.audit.genes import GeneRow
from veupathdb_mcp.audit.pseudogene_calls import (
    FAMILY_WORDS,
    GenomePseudogeneCalls,
    UnpairedCounts,
    pseudogene_calls_of,
)
from veupathdb_mcp.tools import audit_genome_pseudogene_calls_tools
from veupathdb_mcp.tools.audit_genome_pseudogene_calls_tools import (
    audit_genome_pseudogene_calls,
)

NF54 = "Plasmodium falciparum NF54"


def recorded(abbrev: str) -> WDKAnswer:
    path = FIXTURES / f"pseudogene_calls_{abbrev}.json"
    return WDKAnswer.model_validate_json(path.read_text())


async def test_the_recorded_nf54_genome_pairs_26_calls_with_3d7(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = serve(monkeypatch, [recorded("pfalNF54"), recorded("pfal3D7")])

    result = await audit_genome_pseudogene_calls("plasmodb", NF54, PF3D7)

    assert [
        (search, json.loads(config.parameters["organism"]))
        for _, search, config, _ in site.searches
    ] == [("GenesByTaxon", [NF54]), ("GenesByTaxon", [PF3D7])]
    assert (result.organism, result.reference_organism) == (NF54, PF3D7)
    assert (result.genes, result.pseudogenes, result.unflagged) == (5609, 229, 0)
    assert (result.reference_genes, result.reference_unflagged) == (5720, 0)
    assert result.no_gene_flagged is False
    assert len(result.calls) == 26
    assert result.unpaired == UnpairedCounts(
        family_word=160, no_reference=35, several_references=8
    )
    assert Counter(call.basis for call in result.calls) == {"PRODUCT": 26}
    assert Counter(gene.reason for gene in result.unpaired_genes) == {
        "FAMILY_WORD": 160,
        "NO_REFERENCE": 35,
        "SEVERAL_REFERENCES": 8,
    }
    pairs = {call.pseudogene: call.reference_gene for call in result.calls}
    assert pairs["PfNF54_100037200:pseudogene"] == "PF3D7_1032400"
    assert pairs["PfNF54_130076100"] == "PF3D7_1372200"
    assert pairs["PfNF54_000005300:pseudogene"] == "PF3D7_API03600"
    assert len(set(pairs.values())) == 26


async def test_the_recorded_calls_leave_out_family_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, [recorded("pfalNF54"), recorded("pfal3D7")])

    result = await audit_genome_pseudogene_calls("plasmodb", NF54, PF3D7)

    products = {call.product for call in result.calls}
    assert "erythrocyte membrane protein 1, PfEMP1" not in products
    assert "histidine-rich protein III" in products
    assert all("unknown function" not in product for product in products)


async def test_a_site_error_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refused(site_id: str, organism: str) -> list[GeneRow]:
        detail = f"Number of selected values (0) for {organism}"
        raise WDKError(detail=detail)

    monkeypatch.setattr(pseudogene_calls_inputs, "genes_of_genome", refused)

    with pytest.raises(ToolError, match="Number of selected values"):
        await audit_genome_pseudogene_calls("plasmodb", "Plasmodium nonesuch", PF3D7)


async def test_a_site_that_does_not_answer_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def silent(site_id: str, organism: str) -> list[GeneRow]:
        reason = "read timed out"
        raise httpx.ReadTimeout(reason)

    monkeypatch.setattr(pseudogene_calls_inputs, "genes_of_genome", silent)

    with pytest.raises(ToolError, match="plasmodb did not answer the audit reads"):
        await audit_genome_pseudogene_calls("plasmodb", NF54, PF3D7)


async def test_the_pairing_runs_in_an_audit_slot_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, [recorded("pfalNF54"), recorded("pfal3D7")])
    threads: list[int] = []

    def pair(
        organism: str,
        reference_organism: str,
        genome: list[GeneRow],
        reference: list[GeneRow],
    ) -> GenomePseudogeneCalls:
        threads.append(threading.get_ident())
        return pseudogene_calls_of(organism, reference_organism, genome, reference)

    monkeypatch.setattr(
        audit_genome_pseudogene_calls_tools, "pseudogene_calls_of", pair
    )

    result = await audit_genome_pseudogene_calls("plasmodb", NF54, PF3D7)

    assert len(result.calls) == 26
    [thread] = threads
    assert thread != threading.get_ident()


def test_the_description_lists_exactly_the_family_words() -> None:
    tool = Tool.from_function(audit_genome_pseudogene_calls)
    words = " ".join((tool.description or "").split())
    listed = re.search(r"The words are: (.*?), so a product", words)

    assert listed is not None
    assert tuple(re.findall(r"'([^']*)'", listed.group(1))) == FAMILY_WORDS


def test_the_description_follows_a_changed_word_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit_genome_pseudogene_calls_tools, "FAMILY_WORDS", ("rifin", "stevor")
    )

    described = audit_genome_pseudogene_calls_tools.description()

    assert "The words are: 'rifin' and 'stevor', so a product" in " ".join(
        described.split()
    )
