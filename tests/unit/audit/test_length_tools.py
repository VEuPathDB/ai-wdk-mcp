from collections.abc import Callable
from typing import Literal

import pytest
from fastmcp.exceptions import ToolError
from tests._support.audit_site import AuditSite, Contig, window_refused
from tests._support.length_site import (
    FLANK,
    PART_A,
    PART_B,
    REFERENCE,
    length_group,
    split_site,
)
from tests._support.proteins import PROTEIN, back_translate, row
from veupathdb.wdk import WDKAnswer

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.codes import GeneticCode, reverse_complement
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.audit.genes import GeneRow, rows_of
from veupathdb_mcp.audit.pseudogene import CdsPart
from veupathdb_mcp.tools import audit_tools

ME = "PCYB_1"
SHORT_PROTEIN = PROTEIN[:60] + PROTEIN[140:]


class Gene:
    def __init__(self, contig: str, cds: list[CdsPart], start: int, end: int) -> None:
        self.contig = contig
        self.cds = cds
        self.start = start
        self.end = end

    def minus(self) -> "Gene":
        size = len(self.contig)
        return Gene(
            reverse_complement(self.contig),
            sorted(
                (
                    CdsPart(start=size - p.end + 1, end=size - p.start + 1)
                    for p in self.cds
                ),
                key=lambda p: p.start,
            ),
            size - self.end + 1,
            size - self.start + 1,
        )


def tga_for_w(protein: str) -> str:
    return "".join("TGA" if a == "W" else back_translate(a) for a in protein)


def short_gene(
    middle: str, left: int = FLANK, encode: Callable[[str], str] = back_translate
) -> Gene:
    first = encode(PROTEIN[:60])
    last = encode(PROTEIN[140:]) + "TAA"
    start = left + 1
    end = left + len(first) + len(middle) + len(last)
    return Gene(
        "C" * left + first + middle + last + "C" * FLANK,
        [
            CdsPart(start=start, end=start + len(first) - 1),
            CdsPart(start=end - len(last) + 1, end=end),
        ],
        start,
        end,
    )


def short_site(
    monkeypatch: pytest.MonkeyPatch,
    gene: Gene,
    *,
    strand: Literal["+", "-"] = "+",
    others: int = 8,
) -> AuditSite:
    site = AuditSite(monkeypatch)
    me = row(ME, "Plasmodium cynomolgi strain B", len(SHORT_PROTEIN), strand=strand)
    me = me.model_copy(update={"start": gene.start, "end": gene.end})
    site.rows = length_group([me], others)
    site.orthologs[ME] = site.rows
    site.proteins = {ME: SHORT_PROTEIN, REFERENCE: PROTEIN}
    site.models[ME] = GeneModel(organism_abbrev="pcynB", cds=gene.cds)
    site.contigs["pcynB", me.sequence_id] = Contig.whole(gene.contig)
    return site


async def test_a_short_gene_whose_genome_holds_the_segment_is_genome_encodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gene = short_gene(back_translate(PROTEIN[60:140]))
    site = short_site(monkeypatch, gene)

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "GENOME_ENCODES"
    assert result.counts == {"model": 12, "genome_same_strand": 7}
    assert result.track == "MMMMMMGGGGGGGMMMMMM"
    assert (result.length_class, result.ratio) == ("SHORT", 0.6)
    assert (result.group_median, result.organisms) == (200, 10)
    assert (result.genes, result.reference_gene) == ([ME], REFERENCE)
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert not result.at_contig_edge
    assert site.windows == [
        ("pcynB", "PCYB_1_contig", gene.start - 6000, gene.end + 6000)
    ]


async def test_a_minus_strand_gene_is_read_on_its_own_strand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gene = short_gene(back_translate(PROTEIN[60:140])).minus()
    site = short_site(monkeypatch, gene, strand="-")

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "GENOME_ENCODES"
    assert result.counts == {"model": 12, "genome_same_strand": 7}
    assert result.track == "MMMMMMGGGGGGGMMMMMM"
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, True)
    assert site.windows == [
        ("pcynB", "PCYB_1_contig", gene.start - 6000, gene.end + 6000)
    ]


async def test_a_segment_the_genome_lacks_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_site(monkeypatch, short_gene("C" * 240))

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "ABSENT"


async def test_a_missing_segment_near_a_contig_end_is_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gene = short_gene("C" * 240, left=1000)
    site = short_site(monkeypatch, gene)

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "ASSEMBLY"
    assert result.at_contig_edge
    assert result.ns_in_window == 0
    assert site.lengths_read == [("pcynB", "PCYB_1_contig")]


async def test_a_missing_segment_over_ns_is_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_site(monkeypatch, short_gene("N" * 240))

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "ASSEMBLY"
    assert result.ns_in_window == 240
    assert not result.at_contig_edge


async def test_the_code_is_inferred_from_the_genes_own_cds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_site(monkeypatch, short_gene(tga_for_w(PROTEIN[60:140]), encode=tga_for_w))

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert (result.code, result.code_inferred) == (GeneticCode.UGA_TRYPTOPHAN, True)
    assert result.verdict == "GENOME_ENCODES"


async def test_a_cds_the_protein_does_not_explain_reads_the_standard_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gene = short_gene(back_translate(PROTEIN[60:140]))
    site = short_site(monkeypatch, gene)
    site.models[ME] = GeneModel(
        organism_abbrev="pcynB",
        cds=[CdsPart(start=gene.start + 3, end=gene.start + 32)],
    )

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, False)


async def test_a_model_with_no_cds_row_is_checked_and_its_model_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_site(monkeypatch, short_gene(back_translate(PROTEIN[60:140])))
    site.models[ME] = GeneModel(organism_abbrev="pcynB", cds=[])

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert result.verdict == "GENOME_ENCODES"
    assert (result.code, result.code_inferred) == (GeneticCode.STANDARD, False)
    assert site.models_read == [ME]
    assert result.models == [None]
    assert result.evidence_unread == [f"the GeneModelDump of {ME} gives no CDS row"]


@pytest.mark.parametrize(
    ("others", "length", "length_class"),
    [(4, 120, "UNQUALIFIED"), (8, 190, "TYPICAL"), (8, 400, "LONG")],
)
async def test_a_gene_the_group_does_not_call_short_reads_no_genome(
    monkeypatch: pytest.MonkeyPatch, others: int, length: int, length_class: str
) -> None:
    site = short_site(monkeypatch, short_gene("C" * 240), others=others)
    site.rows[0] = site.rows[0].model_copy(update={"protein_length": length})
    site.orthologs[ME] = site.rows

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert (result.verdict, result.length_class) == ("NOT_CHECKED", length_class)
    assert (result.windows, result.counts, result.track) == (0, {}, "")
    assert (result.ns_in_window, result.at_contig_edge, result.code) == (
        None,
        None,
        None,
    )
    assert result.reference_gene == REFERENCE
    assert site.proteins_read == []
    assert site.models_read == []
    assert result.models == []
    assert site.windows == []
    assert site.lengths_read == []


async def test_a_short_gene_beside_a_paralog_reads_no_genome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_site(monkeypatch, short_gene(back_translate(PROTEIN[60:140])))
    paralog = row("PCYB_2", "Plasmodium cynomolgi strain B", 200, start=60001)
    site.rows.append(paralog)
    site.orthologs[ME] = site.rows

    result = await audit_tools.audit_gene_length("plasmodb", ME)

    assert (result.verdict, result.length_class) == ("NOT_CHECKED", "UNQUALIFIED")
    assert site.proteins_read == []
    assert site.windows == []


async def test_a_length_window_over_the_limit_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_site(monkeypatch, short_gene("C" * 240))
    me = site.rows[0]
    site.rows[0] = me.model_copy(
        update={"end": me.start + served.AUDIT_MAX_WINDOW_BASES}
    )
    site.orthologs[ME] = site.rows
    length = served.AUDIT_MAX_WINDOW_BASES + 1 + 2 * 6000

    with pytest.raises(ToolError, match=window_refused(ME, length)):
        await audit_tools.audit_gene_length("plasmodb", ME)

    assert site.proteins_read == []
    assert site.models_read == []
    assert site.windows == []


async def test_a_reference_without_a_protein_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_site(monkeypatch, short_gene("C" * 240))
    del site.proteins[REFERENCE]

    with pytest.raises(ToolError, match="PCYM_1 has no protein on plasmodb"):
        await audit_tools.audit_gene_length("plasmodb", ME)

    assert site.windows == []


async def test_an_unknown_length_gene_is_a_tool_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_site(monkeypatch, short_gene("C" * 240))

    with pytest.raises(ToolError, match="PCYB_9 names no gene of plasmodb"):
        await audit_tools.audit_gene_length("plasmodb", "PCYB_9")


async def test_two_neighbours_that_hold_the_reference_are_a_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = split_site(monkeypatch)

    result = await audit_tools.audit_gene_split("plasmodb", PART_A, PART_B)

    assert result.verdict == "SPLIT_CONFIRMED"
    assert (result.length_class, result.ratio) == ("SPLIT", 1.0)
    assert result.genes == [PART_A, PART_B]
    assert result.counts == {"part1": 9, "genome_same_strand": 1, "part2": 9}
    assert result.track == "1" * 9 + "G" + "2" * 9
    assert site.models_read == [PART_A, PART_B]
    assert [(m.gene, m.cds) for m in result.models] == [
        (PART_A, [(site.rows[0].start, site.rows[0].end)]),
        (PART_B, [(site.rows[1].start, site.rows[1].end)]),
    ]
    [(_, _, start, end)] = site.windows
    assert (start, end) == (site.rows[0].start - 6000, site.rows[1].end + 6000)


@pytest.mark.parametrize(
    ("update", "named"),
    [
        ({"strand": "-"}, "do not lie on one strand of one sequence"),
        ({"sequence_id": "other"}, "do not lie on one strand of one sequence"),
        ({"start": 200000, "end": 200302}, "lie 159697 bases apart"),
    ],
)
async def test_a_pair_that_is_not_neighbours_on_one_strand_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch, update: dict[str, object], named: str
) -> None:
    site = split_site(monkeypatch)
    site.rows[1] = site.rows[1].model_copy(update=update)

    with pytest.raises(ToolError, match=named):
        await audit_tools.audit_gene_split("plasmodb", PART_A, PART_B)

    assert site.windows == []


@pytest.mark.parametrize(("apart", "refused"), [(20000, False), (20001, True)])
async def test_a_split_pair_lies_at_most_twenty_kilobases_apart(
    monkeypatch: pytest.MonkeyPatch, apart: int, refused: bool
) -> None:
    site = split_site(monkeypatch)
    a, b = site.rows[0], site.rows[1]
    start = a.end + apart
    site.rows[1] = b.model_copy(update={"start": start, "end": start + 302})

    if refused:
        with pytest.raises(ToolError, match=f"lie {apart} bases apart"):
            await audit_tools.audit_gene_split("plasmodb", PART_A, PART_B)
        assert site.windows == []
    else:
        result = await audit_tools.audit_gene_split("plasmodb", PART_A, PART_B)
        assert result.length_class == "SPLIT"
        assert len(site.windows) == 1


async def test_a_neighbour_outside_the_group_reads_no_genome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = split_site(monkeypatch)
    site.orthologs[PART_A] = [r for r in site.rows if r.gene != PART_B]

    result = await audit_tools.audit_gene_split("plasmodb", PART_A, PART_B)

    assert (result.verdict, result.length_class) == ("NOT_CHECKED", "UNQUALIFIED")
    assert site.proteins_read == []
    assert site.windows == []


async def test_a_pair_that_names_one_gene_twice_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = split_site(monkeypatch)

    with pytest.raises(ToolError, match="names PCYB_A twice"):
        await audit_tools.audit_gene_split("plasmodb", PART_A, PART_A)

    assert site.windows == []


@pytest.mark.parametrize("genes", [[], [PART_A, PART_B, REFERENCE]])
async def test_a_length_reader_takes_one_gene_or_a_pair(
    monkeypatch: pytest.MonkeyPatch, genes: list[str]
) -> None:
    site = split_site(monkeypatch)

    with pytest.raises(ValueError, match=f"one gene or a pair, not {len(genes)}"):
        await served.length_inputs("plasmodb", genes)

    assert site.windows == []


async def test_a_gene_row_the_site_serves_unreadable_is_a_named_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = short_site(monkeypatch, short_gene("C" * 240))
    bad = WDKAnswer.model_validate(
        {
            "meta": {"totalCount": 1, "responseCount": 1},
            "records": [
                {
                    "id": [
                        {"name": "gene_source_id", "value": REFERENCE},
                        {"name": "source_id", "value": f"{REFERENCE}.1"},
                    ],
                    "attributes": {"is_pseudo": "maybe"},
                }
            ],
        }
    )

    async def unreadable(site_id: str, gene: str) -> list[GeneRow]:
        return rows_of(bad, "GeneByLocusTag")

    monkeypatch.setattr(served, "orthologs_of", unreadable)

    with pytest.raises(
        ToolError, match=f"source_id={REFERENCE}.1. that is not a gene row"
    ):
        await audit_tools.audit_gene_length("plasmodb", ME)

    assert site.windows == []
