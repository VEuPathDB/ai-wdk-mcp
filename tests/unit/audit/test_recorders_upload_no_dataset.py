import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import pytest
from pydantic import JsonValue
from scripts import (
    record_audit_fusion,
    record_audit_selenoprotein,
    record_audit_strain,
)
from scripts.record_audit_fusion import CASES, FusionRecording, models_read
from scripts.record_audit_missing import RecordCall
from scripts.record_audit_records import read_wire
from scripts.record_audit_strain import PAIRS, StrainWire, model_rows
from tests._support.audit_wire import FIXTURES
from tests._support.missing_wire import replay_record_reads
from veupathdb import get_observer, set_observer
from veupathdb.wdk import StrategyAPI, WDKRecordInstance

from veupathdb_mcp.audit import (
    gene_ids,
    gene_models,
    genes,
    record_reads,
    served,
)


def _upload(*_: object, **__: object) -> NoReturn:
    msg = "a recorder reached the dataset upload"
    raise AssertionError(msg)


class RecordedApi:
    def __init__(self, bodies: dict[str, JsonValue]) -> None:
        self._bodies = bodies
        self.read: list[str] = []

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        [gene] = [part["value"] for part in primary_key if part["name"] == "source_id"]
        if gene not in self._bodies:
            msg = f"the recorder sent a read of {gene} the wire does not hold"
            raise AssertionError(msg)
        self.read.append(gene)
        return WDKRecordInstance.model_validate(self._bodies[gene])


async def _signed_in() -> None:
    return None


@pytest.fixture(autouse=True)
def no_upload(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(gene_models, "get_strategy_api", gene_models.get_strategy_api)
    monkeypatch.setattr(record_reads, "get_strategy_api", record_reads.get_strategy_api)
    monkeypatch.setattr(served, "get_jbrowse_client", served.get_jbrowse_client)
    monkeypatch.setattr(gene_ids, "genes_by_text", gene_ids.genes_by_text)
    monkeypatch.setattr(StrategyAPI, "create_dataset", _upload)
    monkeypatch.setattr(genes, "dataset_client", _upload)
    for script in (
        record_audit_strain,
        record_audit_fusion,
        record_audit_selenoprotein,
    ):
        monkeypatch.setattr(script, "act_as_the_test_account", _signed_in)
    observer = get_observer()
    yield
    set_observer(observer)


def _copied(into: Path, name: str) -> Path:
    shutil.copy(FIXTURES / name, into / name)
    return into / name


async def test_the_strain_recorder_reads_models_and_uploads_no_dataset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _copied(tmp_path, record_audit_strain.INTRONS_PKAC)
    wires = {
        pair.file: StrainWire.model_validate_json(
            _copied(tmp_path, pair.file).read_text()
        )
        for pair in PAIRS
    }
    bodies = {
        wire.reference: next(
            body for body in wire.records if model_rows([body], wire.reference)
        )
        for wire in wires.values()
    }
    for name, wire in wires.items():
        held = [body for body in wire.records if not model_rows([body], wire.reference)]
        (tmp_path / name).write_text(
            wire.model_copy(update={"records": held}).model_dump_json(indent=1) + "\n"
        )
    api = RecordedApi(bodies)
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: api)

    await record_audit_strain.record_models(tmp_path)

    assert api.read == [wire.reference for wire in wires.values()]
    for name, wire in wires.items():
        rewritten = StrainWire.model_validate_json((tmp_path / name).read_text())
        assert model_rows(rewritten.records, wire.reference) == model_rows(
            wire.records, wire.reference
        )


def test_the_strain_recorder_has_no_mode_that_reads_answers() -> None:
    assert "record" not in vars(record_audit_strain)
    assert "locus_tag_answers" not in vars(record_audit_strain)


async def test_the_fusion_recorder_reads_models_and_uploads_no_dataset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = CASES["pfraNilgiri_rpt6"]
    recorded = FusionRecording.model_validate_json(
        _copied(tmp_path, case.file).read_text()
    )
    bodies: dict[str, JsonValue] = {}
    held = []
    for call in recorded.calls:
        match call:
            case RecordCall(record=body) if models_read([call]):
                [gene] = models_read([call])
                bodies[gene] = body
            case _:
                held.append(call)
    (tmp_path / case.file).write_text(
        recorded.model_copy(update={"calls": held}).model_dump_json(indent=1) + "\n"
    )
    api = RecordedApi(bodies)
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: api)

    await record_audit_fusion.record_models("pfraNilgiri_rpt6", tmp_path)

    rewritten = FusionRecording.model_validate_json((tmp_path / case.file).read_text())
    assert api.read == case.models
    assert models_read(rewritten.calls) == case.models


def held_calls(recording: FusionRecording) -> list[dict[str, object]]:
    return [call.model_dump(exclude={"served_total"}) for call in recording.calls]


async def test_the_fusion_recorder_reruns_the_tool_and_uploads_no_dataset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = CASES["pfraNilgiri_rpt6"]
    recorded = FusionRecording.model_validate_json((FIXTURES / case.file).read_text())
    wire = replay_record_reads(monkeypatch, recorded.calls)
    monkeypatch.setattr(genes, "get_wdk_client", lambda site_id: wire)

    await record_audit_fusion.record("pfraNilgiri_rpt6", tmp_path)

    rewritten = FusionRecording.model_validate_json((tmp_path / case.file).read_text())
    assert wire.calls == []
    assert rewritten.case == recorded.case
    assert held_calls(rewritten) == held_calls(recorded)


async def test_the_selenoprotein_recorder_replays_its_wire_and_uploads_no_dataset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wire = read_wire(_copied(tmp_path, record_audit_selenoprotein.FILE))
    monkeypatch.setattr(
        record_audit_selenoprotein, "get_strategy_api", lambda site_id: RecordedApi({})
    )

    await record_audit_selenoprotein.record(tmp_path)

    assert read_wire(tmp_path / record_audit_selenoprotein.FILE) == wire


async def test_every_gene_list_upload_is_refused_while_a_recorder_runs() -> None:
    with pytest.raises(AssertionError, match="reached the dataset upload"):
        await genes.locus_tag_answers("plasmodb", ["PF3D7_1"], [])
