import typing
from collections.abc import Awaitable, Callable

import pytest
from pydantic import AliasChoices, BaseModel, JsonValue, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from scripts.record_audit_fusion import CASES, FusionRecording
from scripts.record_audit_strain import StrainWire
from tests._support import anatomy_site, fusion_site, piga_selk_site
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
from tests._support.group_cloud_site import (
    CloudSite,
    recorded,
    recorded_tree,
    serve_clouds,
    total_of,
)
from tests._support.group_count_site import install
from tests._support.intron_wire import Served, load_introns
from tests._support.length_site import PART_A, PART_B, split_site
from tests._support.missing_wire import (
    recording,
    replay_record_reads,
    replay_records,
)
from tests._support.organelle_fixtures import CYTB, recorded_site
from tests._support.phyletic_truth import site_counts, synthetic_groups, synthetic_tree
from tests._support.proteins import PROTEIN, back_translate
from tests._support.record_site import (
    install_recorded_records,
    install_store,
    load_records,
)
from tests._support.row_reads import serve_recorded_rows
from tests._support.selenoprotein_wire import SelenoproteinWire
from tests._support.strain_site import (
    REFERENCE,
    STRAIN,
    install_annotation,
    strain_site,
)
from tests._support.wdk_genes import PF3D7, ReportSite, answer_of, serve
from veupathdb.wdk import WDKAnswer

from veupathdb_mcp import server
from veupathdb_mcp.audit import genes, served
from veupathdb_mcp.audit.gene_models import GeneModel
from veupathdb_mcp.catalog import PhyleticPattern
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
from veupathdb_mcp.wdk import phyletic_counts

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
    site = piga_selk_site.Site(monkeypatch)
    site.exonless.add(PIGA)
    exonless = await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA)
    monkeypatch.setattr(audit_tools, "pseudogene_inputs", piga_inputs)
    return [
        await audit_tools.audit_pseudogene_call("plasmodb", NF54_PIGA, PIGA),
        exonless,
    ]


async def selenoprotein_end(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    SelenoproteinWire(monkeypatch)
    recorded = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)
    monkeypatch.setattr(audit_tools, "selenoprotein_inputs", selk_inputs)
    faked = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)
    site = piga_selk_site.Site(monkeypatch)
    site.exonless.add(ME49_SELK)
    monkeypatch.setattr(
        audit_tools, "selenoprotein_inputs", served.selenoprotein_inputs
    )
    exonless = await audit_tools.audit_selenoprotein_end("toxodb", GT1_SELK, ME49_SELK)
    return [recorded, faked, exonless]


async def gene_length(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    wire = load_wire("pcynM_pkac_length.json")
    install_records(monkeypatch, wire)
    install_genome(monkeypatch, wire, "pcynM", "PcyM_07")
    serve_recorded_rows(monkeypatch, wire.gene_answers)
    unqualified = await audit_tools.audit_gene_length("plasmodb", "PcyM_0736700")
    site = split_site(monkeypatch)
    split = await audit_tools.audit_gene_split("plasmodb", PART_A, PART_B)
    site.models[PART_B] = GeneModel(organism_abbrev="pcynB", cds=[])
    uncoded = await audit_tools.audit_gene_split("plasmodb", PART_A, PART_B)
    return [unqualified, split, uncoded]


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
    recorded = await audit_strain_tools.audit_strain_model(
        "plasmodb", "PcyM_0736700", "PCYB_074210"
    )
    site = strain_site(
        monkeypatch,
        (PROTEIN[:60] + PROTEIN[140:], PROTEIN),
        intron=back_translate(PROTEIN[60:140]),
    )
    site.models[STRAIN] = GeneModel(organism_abbrev="pfalDd2", cds=[])
    uncoded = await audit_strain_tools.audit_strain_model("plasmodb", STRAIN, REFERENCE)
    return [recorded, uncoded]


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
    rpt6, pbgs = (
        FusionRecording.model_validate_json((FIXTURES / CASES[case].file).read_text())
        for case in ("pfraNilgiri_rpt6", "tgonME49_pbgs")
    )
    replay_record_reads(monkeypatch, rpt6.calls)
    found.append(await audit_fusion_tools.audit_gene_fusion("plasmodb", "AK88_02763"))
    replay_records(monkeypatch, pbgs.calls, 2)
    found.append(await audit_fusion_tools.audit_gene_fusion("toxodb", "TGME49_500302"))
    fake = fusion_site.fusion_site(
        monkeypatch, fusion_site.REFERENCE + fusion_site.NEIGHBOUR
    )
    fake.exonless.add(fusion_site.BESIDE_REFERENCE[2])
    found.append(
        await audit_fusion_tools.audit_gene_fusion("plasmodb", fusion_site.MEMBER)
    )
    return found


async def phyletic_expression(monkeypatch: pytest.MonkeyPatch) -> list[BaseModel]:
    tree = synthetic_tree()
    install(monkeypatch, site_counts(tree, synthetic_groups()), tree)
    pattern = TypeAdapter(PhyleticPattern).validate_python(
        {
            "kind": "compare",
            "left": {"kind": "codes", "codes": ["XG"]},
            "right": {"kind": "all_except", "codes": ["XA"]},
            "reading": "averages",
            "condition": "more_than",
        }
    )
    written = await catalog_tools.build_phyletic_expression("orthomcl", pattern)
    return [written, await _computed_comparison(monkeypatch)]


async def _computed_comparison(monkeypatch: pytest.MonkeyPatch) -> BaseModel:
    tgon, pfal = frozenset({"tgon"}), frozenset({"pfal"})
    clouds: dict[frozenset[str], JsonValue] = {
        tgon: recorded("r02_tgon_groupcloud"),
        pfal: recorded("r02_pfal_groupcloud"),
    }
    records = {tgon: total_of("r02_tgon_std"), pfal: total_of("r02_pfal_std")}
    serve_clouds(monkeypatch, CloudSite(clouds, records, len), recorded_tree())

    async def too_large(site_id: str, pattern: PhyleticPattern) -> bool:
        del site_id, pattern
        return True

    monkeypatch.setattr(phyletic_counts, "least_expression_too_large", too_large)
    pattern = TypeAdapter(PhyleticPattern).validate_python(
        {
            "kind": "compare",
            "left": {"kind": "codes", "codes": ["tgon"]},
            "right": {"kind": "codes", "codes": ["pfal"]},
            "reading": "per_genome",
            "condition": "more_than",
        }
    )
    return await catalog_tools.build_phyletic_expression("orthomcl", pattern)


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
    "build_phyletic_expression": phyletic_expression,
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


GENE_MODEL_FIELDS: dict[str, dict[str, object]] = {
    "audit_intron_support": {"model": None},
    "audit_gene_length": {"models": [], "evidenceUnread": []},
    "audit_pseudogene_call": {"referenceModel": None, "evidenceUnread": []},
    "audit_strain_model": {"models": [], "evidenceUnread": []},
    "audit_gene_fusion": {"models": [], "evidenceUnread": [], "merged": None},
    "audit_selenoprotein_end": {"models": [], "evidenceUnread": []},
}


@pytest.mark.parametrize("tool", sorted(GENE_MODEL_FIELDS))
async def test_a_result_stored_before_the_gene_models_reads_none_read(
    monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    unread = GENE_MODEL_FIELDS[tool]
    results = await RECORDED[tool](monkeypatch)
    stored = [result.model_dump(by_alias=True, mode="json") for result in results]

    for result, dumped in zip(results, stored, strict=True):
        older = {key: value for key, value in dumped.items() if key not in unread}
        validated = type(result).model_validate(older)
        assert validated.model_dump(by_alias=True, mode="json") == older | unread
    assert {
        key for dumped in stored for key in unread if dumped[key] != unread[key]
    } == set(unread)


async def test_an_intron_audit_stored_before_its_corrected_exons_reads_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = await intron_support(monkeypatch)
    stored = [result.model_dump(by_alias=True, mode="json") for result in results]

    for result, dumped in zip(results, stored, strict=True):
        older = {key: value for key, value in dumped.items() if key != "correctedExons"}
        validated = type(result).model_validate(older)
        assert validated.model_dump(by_alias=True, mode="json") == older | {
            "correctedExons": None
        }
    assert [dumped["correctedExons"] is None for dumped in stored] == [
        dumped["correctedCds"] is None for dumped in stored
    ]
    assert sum(dumped["correctedExons"] is not None for dumped in stored) == 4


def misnamed(dumped: dict[str, typing.Any], key: str) -> dict[str, typing.Any]:
    held = dumped[key]
    match held:
        case list() if len(held) > 1:
            return dumped | {key: held[::-1]}
        case list():
            return dumped | {key: [held[0] | {"gene": "OTHER_GENE"}]}
        case _:
            return dumped | {key: held | {"gene": "OTHER_GENE"}}


@pytest.mark.parametrize("tool", sorted(GENE_MODEL_FIELDS))
async def test_a_result_whose_models_name_other_genes_is_refused(
    monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    key = next(iter(GENE_MODEL_FIELDS[tool]))
    results = await RECORDED[tool](monkeypatch)
    [(result, dumped)] = [
        (result, dumped)
        for result in results
        if (dumped := result.model_dump(by_alias=True, mode="json"))[key]
    ][:1]

    with pytest.raises(ValidationError, match=r"gene models name|merged span"):
        type(result).model_validate(misnamed(dumped, key))


async def test_a_fusion_with_models_and_no_merged_span_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [result, *_] = await gene_fusion(monkeypatch)
    dumped = result.model_dump(by_alias=True, mode="json")

    with pytest.raises(ValidationError, match="serves the merged span"):
        type(result).model_validate(dumped | {"merged": None})
