import pytest
from tests._support.audit_wire import (
    answers,
    install_genome,
    install_records,
    load_wire,
)
from tests._support.wdk_genes import serve_private

from veupathdb_mcp.audit import served
from veupathdb_mcp.audit.codes import GeneticCode, infer_code
from veupathdb_mcp.audit.gene_models import gene_model
from veupathdb_mcp.audit.genes import proteins_of, rows_of
from veupathdb_mcp.audit.length import DnaWindow, check_length
from veupathdb_mcp.tools import audit_tools

PKAC = "PcyM_0736700"
PKAC_REFERENCE = "PCYB_074210"
PKAC_FIXTURE = "pcynM_pkac_length.json"


async def test_the_recorded_pkac_group_is_too_varied_to_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = load_wire(PKAC_FIXTURE)
    records = install_records(monkeypatch, wire)
    genome = install_genome(monkeypatch, wire, "pcynM", "PcyM_07")
    _, reports = serve_private(
        monkeypatch, answers([*wire.gene_answers, *wire.row_answers])
    )

    result = await audit_tools.audit_gene_length("plasmodb", PKAC)

    assert (result.verdict, result.length_class) == ("NOT_CHECKED", "UNQUALIFIED")
    assert (result.organisms, result.group_median, result.ratio) == (63, 4008, 0.07)
    assert (result.group_copies, result.group_spread) == (8, 0.092)
    assert (result.reference_gene, result.code, result.code_inferred) == (
        None,
        None,
        False,
    )
    assert (result.windows, result.counts) == (0, {})
    assert records.reads == [["Orthologs"]]
    assert [len(d.source_content.ids) for d in reports.datasets] == [
        1,
        150,
        150,
        150,
        73,
    ]
    assert genome.windows == []
    assert genome.lengths_read == []


async def test_the_recorded_pkac_genome_encodes_its_missing_exon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = load_wire(PKAC_FIXTURE)
    install_records(monkeypatch, wire)
    serve_private(monkeypatch, answers(wire.protein_answers))
    [me] = rows_of(answers(wire.gene_answers)[0], "GeneByLocusTag")
    proteins = await proteins_of("plasmodb", [PKAC, PKAC_REFERENCE])
    model = await gene_model("plasmodb", PKAC)
    first = me.start - served.LENGTH_MIN_FLANK - wire.window_start
    last = me.end + served.LENGTH_MIN_FLANK - wire.window_start + 1
    cds = "".join(
        wire.window[p.start - wire.window_start : p.end - wire.window_start + 1]
        for p in model.cds
    )
    code = infer_code(cds, proteins[PKAC])

    result = check_length(
        proteins[PKAC_REFERENCE],
        [proteins[PKAC]],
        DnaWindow(
            sequence=wire.window[first:last], strand=me.strand, at_contig_edge=False
        ),
        code or GeneticCode.STANDARD,
    )

    assert (me.strand, me.sequence_id, model.organism_abbrev) == (
        "+",
        "PcyM_07",
        "pcynM",
    )
    assert (len(proteins[PKAC]), len(proteins[PKAC_REFERENCE])) == (280, 341)
    assert len(model.cds) == 4
    assert code == GeneticCode.STANDARD
    assert result.verdict == "GENOME_ENCODES"
    assert result.counts == {"model": 27, "genome_same_strand": 5, "weak": 1}
    assert result.track == "MMMMGGGGGw" + "M" * 23
