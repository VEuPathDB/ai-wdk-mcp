from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts import record_gene_lookups
from scripts.record_audit_records import RecordWire
from scripts.record_gene_lookups import FILE, FIXTURES, LookupWire
from tests._support.record_site import RecordedRecords
from veupathdb import get_observer, set_observer
from veupathdb.wdk import StrategyAPI

from veupathdb_mcp.audit import gene_ids, gene_models, genes, record_reads
from veupathdb_mcp.gene_lookup import wdk


async def _signed_in() -> None:
    return None


@pytest.fixture(autouse=True)
def restored(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(gene_models, "get_strategy_api", gene_models.get_strategy_api)
    monkeypatch.setattr(record_reads, "get_strategy_api", record_reads.get_strategy_api)
    monkeypatch.setattr(gene_ids, "genes_by_text", gene_ids.genes_by_text)
    monkeypatch.setattr(StrategyAPI, "create_dataset", StrategyAPI.create_dataset)
    monkeypatch.setattr(genes, "dataset_client", genes.dataset_client)
    monkeypatch.setattr(wdk, "dataset_client", wdk.dataset_client)
    monkeypatch.setattr(record_gene_lookups, "act_as_the_test_account", _signed_in)
    observer = get_observer()
    yield
    set_observer(observer)


async def test_the_recorder_reads_records_alone_and_writes_its_wire_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded = LookupWire.model_validate_json((FIXTURES / FILE).read_text())
    site = RecordedRecords(
        RecordWire(site=recorded.site, transcript_key=[], records=recorded.records)
    )
    monkeypatch.setattr(record_gene_lookups, "get_strategy_api", lambda site_id: site)

    await record_gene_lookups.record(tmp_path)

    assert (tmp_path / FILE).read_text() == (FIXTURES / FILE).read_text()
    assert [read[1] for read in site.reads] == [
        *recorded.resolved,
        *recorded.hydrated,
    ]


async def test_every_upload_is_refused_while_the_recorder_runs() -> None:
    record_gene_lookups.tape_the_reads(
        record_gene_lookups.RecordTape(_signed_in, [], 0)
    )

    with pytest.raises(record_gene_lookups.RecordingStoppedError):
        await genes.locus_tag_answers("plasmodb", ["PF3D7_1"], [])
    with pytest.raises(record_gene_lookups.RecordingStoppedError):
        await wdk.resolve_gene_ids("plasmodb", ["PF3D7_1"])
