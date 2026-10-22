import typing
from collections.abc import Awaitable, Callable

import pytest
from pydantic import AliasChoices, BaseModel
from pydantic.fields import FieldInfo
from scripts.record_audit_fusion import CASES, FusionRecording
from scripts.record_audit_strain import StrainWire
from tests._support import anatomy_site
from tests._support.audit_fixtures import (
    GT1_SELK,
    ME49_SELK,
    NF54_PIGA,
    PIGA,
    piga_inputs,
    selk_inputs,
)
from tests._support.audit_wire import (
    FIXTURES,
    install_genome,
    install_records,
    load_wire,
)
from tests._support.busco import served_organisms
from tests._support.evidence_site import (
    DMAW,
    GLO1,
    K13,
    NF54,
    EvidenceSite,
    gene_record,
)
from tests._support.group_count_site import install, install_recorded
from tests._support.intron_wire import Served, load_introns
from tests._support.missing_wire import recording, replay_records
from tests._support.organelle_fixtures import CYTB, recorded_site
from tests._support.record_site import (
    install_recorded_records,
    install_store,
    load_records,
)
from tests._support.row_reads import serve_recorded_rows
from tests._support.strain_site import install_annotation
from tests._support.wdk_genes import PF3D7, ReportSite, answer_of, serve
from veupathdb.wdk import WDKAnswer

from veupathdb_mcp import server
from veupathdb_mcp.audit import genes
from veupathdb_mcp.research import server as research_server
from veupathdb_mcp.tools import (
    audit_anatomy_tools,
    audit_busco_tools,
    audit_evidence_tools,
    audit_fusion_tools,
    audit_genome_pseudogene_calls_tools,
    audit_intron_tools,
    audit_missing_tools,
    audit_organelle_tools,
    audit_strain_tools,
    audit_tools,
    catalog_tools,
)

type Recorded = Callable[[pytest.MonkeyPatch], Awaitable[list[BaseModel]]]

SERVED = {row.fn.__name__: row.fn for row in (*server.TOOLS, *research_server.TOOLS)}


def models_in(annotation: object, found: set[type[BaseModel]]) -> set[type[BaseModel]]:
    match annotation:
        case type() if issubclass(annotation, BaseModel) and annotation not in found:
            found.add(annotation)
            for field in annotation.model_fields.values():
                models_in(field.annotation, found)
        case typing.TypeAliasType():
            models_in(annotation.__value__, found)
        case _:
            for argument in typing.get_args(annotation):
                models_in(argument, found)
    return found


def dump_key(name: str, field: FieldInfo) -> str:
    return field.serialization_alias or field.alias or name


def read_keys(model: type[BaseModel], name: str, field: FieldInfo) -> set[str]:
    by_name = {name} if model.model_config.get("validate_by_name") else set()
    match field.validation_alias:
        case str() as alias:
            return {alias, *by_name}
        case AliasChoices(choices=choices):
            return {c for c in choices if isinstance(c, str)} | by_name
        case _:
            return {field.alias or name, *by_name}


def unread_dump_keys(model: type[BaseModel]) -> list[str]:
    return [
        f"{model.__name__}.{name} dumps {dump_key(name, field)!r}"
        for name, field in model.model_fields.items()
        if not field.exclude
        and dump_key(name, field) not in read_keys(model, name, field)
    ]


async def pseudogene_call(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    monkeypatch.setattr(audit_tools, "pseudogene_inputs", piga_inputs)
    return [await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)]


async def selenoprotein_end(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    monkeypatch.setattr(audit_tools, "selenoprotein_inputs", selk_inputs)
    return [await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)]


async def gene_length(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    wire = load_wire("pcynM_pkac_length.json")
    install_records(monkeypatch, wire)
    install_genome(monkeypatch, wire, "pcynM", "PcyM_07")
    serve_recorded_rows(monkeypatch, wire.gene_answers)
    return [await audit_tools.audit_gene_length("plasmodb", "PcyM_0736700")]


async def strain_model(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    wire = StrainWire.model_validate_json(
        (FIXTURES / "strain_pcynM_pkac.json").read_text()
    )
    install_records(monkeypatch, wire)
    install_genome(monkeypatch, wire, "pcynM", "PcyM_07")
    install_annotation(monkeypatch, wire.annotation)
    serve_recorded_rows(
        monkeypatch, [*wire.gene_answers, *wire.row_answers], wire.protein_answers
    )
    return [
        await audit_strain_tools.audit_strain_model(
            "plasmodb", "PcyM_0736700", "PCYB_074210"
        )
    ]


async def missing_gene(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    replay_records(monkeypatch, recording("missing_tgonGT1_nac.json").calls, 2)
    return [
        await audit_missing_tools.audit_missing_gene(
            "toxodb", "TGARI_257090", "Toxoplasma gondii GT1"
        )
    ]


async def organelle_gene(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    recorded_site(monkeypatch)
    return [
        await audit_organelle_tools.audit_organelle_gene(
            "plasmodb", "Plasmodium falciparum NF54", "CM019798.1", CYTB
        )
    ]


async def genome_priority(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    site = ReportSite([answer_of(served_organisms())])
    monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: site)
    return [await audit_busco_tools.audit_genome_priority("plasmodb")]


async def pseudogene_anatomy(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    anatomy_site.AnatomySite(monkeypatch, anatomy_site.PIGA_FILE)
    return [
        await audit_anatomy_tools.audit_pseudogene_anatomy(
            "plasmodb", anatomy_site.NF54_PIGA, PIGA
        )
    ]


async def genome_pseudogene_calls(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    serve(
        monkeypatch,
        [
            WDKAnswer.model_validate_json(
                (FIXTURES / f"pseudogene_calls_{abbrev}.json").read_text()
            )
            for abbrev in ("pfalNF54", "pfal3D7")
        ],
    )
    return [
        await audit_genome_pseudogene_calls_tools.audit_genome_pseudogene_calls(
            "plasmodb", NF54, PF3D7
        )
    ]


async def gene_evidence(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    found: list[BaseModel] = []
    for site_id, gene, name in (
        ("plasmodb", PIGA, "evidence_pfal3D7_piga.json"),
        ("plasmodb", K13, "evidence_pfal3D7_k13.json"),
        ("tritrypdb", GLO1, "evidence_lmajFriedlin_glo1.json"),
        ("fungidb", DMAW, "evidence_afumAf293_dmaw.json"),
    ):
        site = EvidenceSite(monkeypatch, site_id)
        site.records[gene] = gene_record(name)
        found.append(await audit_evidence_tools.audit_gene_evidence(site_id, gene))
    return found


async def genome_provenance(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    EvidenceSite(monkeypatch, "plasmodb")
    return [await audit_evidence_tools.audit_genome_provenance("plasmodb", NF54)]


async def intron_support(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    found: list[BaseModel] = []
    for site_id, gene, name in (
        ("plasmodb", "PcyM_0736700", "introns_pcynM_pkac.json"),
        ("fungidb", DMAW, "introns_afumAf293_dmaw.json"),
    ):
        Served(monkeypatch, load_introns(name), name.replace(".json", "_proteins.json"))
        found.append(await audit_intron_tools.audit_intron_support(site_id, gene))
    for name, gene in (
        ("introns_afumAf293_afu8g00850.json.xz", "Afu8g00850"),
        ("introns_agamPEST_agap007279.json.xz", "AGAP007279"),
        ("introns_tgonME49_tgme49_224540.json.xz", "TGME49_224540"),
        ("introns_agamPEST_agap003685.json.xz", "AGAP003685"),
    ):
        wire = load_records(name)
        install_recorded_records(monkeypatch, wire)
        install_store(monkeypatch, wire)
        found.append(await audit_intron_tools.audit_intron_support(wire.site, gene))
    return found


async def gene_fusion(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    found: list[BaseModel] = []
    for site_id, gene, case, pairs in (
        ("plasmodb", "AK88_02763", "pfraNilgiri_rpt6", 3),
        ("toxodb", "TGME49_500302", "tgonME49_pbgs", 2),
    ):
        recorded = FusionRecording.model_validate_json(
            (FIXTURES / CASES[case].file).read_text()
        )
        replay_records(monkeypatch, recorded.calls, pairs)
        found.append(await audit_fusion_tools.audit_gene_fusion(site_id, gene))
    return found


async def protein_count_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> list[BaseModel]:
    install_recorded(monkeypatch)
    return [
        await catalog_tools.build_protein_count_comparison(
            "orthomcl", "tgon", "pfal", reverse=True
        )
    ]


async def clade_only_expression(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    install(monkeypatch, lambda expression: 41)
    return [
        await catalog_tools.build_clade_only_expression("orthomcl", ["CILI"]),
        await catalog_tools.build_clade_only_expression("orthomcl", ["ecun"], ["MICR"]),
    ]


RECORDED: dict[str, Recorded] = {
    "audit_pseudogene_call": pseudogene_call,
    "audit_selenoprotein_end": selenoprotein_end,
    "audit_gene_length": gene_length,
    "audit_strain_model": strain_model,
    "audit_missing_gene": missing_gene,
    "audit_organelle_gene": organelle_gene,
    "audit_genome_priority": genome_priority,
    "audit_pseudogene_anatomy": pseudogene_anatomy,
    "audit_genome_pseudogene_calls": genome_pseudogene_calls,
    "audit_gene_evidence": gene_evidence,
    "audit_genome_provenance": genome_provenance,
    "audit_intron_support": intron_support,
    "audit_gene_fusion": gene_fusion,
    "build_protein_count_comparison": protein_count_comparison,
    "build_clade_only_expression": clade_only_expression,
}


def test_every_recording_names_a_served_tool() -> None:
    assert set(RECORDED) <= set(SERVED)


@pytest.mark.parametrize("tool", sorted(SERVED))
async def test_a_served_result_validates_its_own_dump(
    monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    returned = typing.get_type_hints(SERVED[tool])["return"]
    models = models_in(returned, set())

    assert [key for model in models for key in unread_dump_keys(model)] == []

    recorder = RECORDED.get(tool)
    results = [] if recorder is None else await recorder(monkeypatch)
    for result in results:
        served = result.model_dump(by_alias=True, mode="json")
        assert type(result).model_validate(served) == result
