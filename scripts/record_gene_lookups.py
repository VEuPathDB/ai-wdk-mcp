import argparse
import asyncio
from pathlib import Path
from typing import NoReturn

import pytest
from pydantic import BaseModel, ConfigDict
from scripts.record_audit_fixtures import act_as_the_test_account
from scripts.record_audit_records import RecordExchange, RecordingStoppedError, Tally
from scripts.record_audit_selenoprotein import RecordTape
from veupathdb import set_observer
from veupathdb.devtools import use_qa_sites
from veupathdb.wdk import StrategyAPI, close_all_clients, get_strategy_api

from veupathdb_mcp.audit import gene_ids, gene_models, genes, record_reads
from veupathdb_mcp.gene_lookup import GeneResult, hydrate, wdk
from veupathdb_mcp.tools.user_tools import resolve_gene_ids_to_records

FIXTURES = Path(__file__).resolve().parent.parent / "tests/unit/gene_lookup/fixtures"
FILE = "lookups_pfal3D7.json"
SITE = "plasmodb"
RESOLVED = ["PF3D7_1133400", "PF10_0316"]
HYDRATED = ["PF3D7_1222600"]
RECORD_BUDGET = 3
WDK_BUDGET = 30


class LookupWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str
    resolved: list[str]
    hydrated: list[str]
    records: list[RecordExchange]


def _refused(*_: object, **__: object) -> NoReturn:
    msg = "a lookup asked for a read the recording does not allow"
    raise RecordingStoppedError(msg)


def tape_the_reads(patch: pytest.MonkeyPatch, records: RecordTape) -> None:
    patch.setattr(gene_models, "get_strategy_api", lambda site_id: records)
    patch.setattr(record_reads, "get_strategy_api", lambda site_id: records)
    patch.setattr(gene_ids, "genes_by_text", _refused)
    patch.setattr(StrategyAPI, "create_dataset", _refused)
    patch.setattr(genes, "dataset_client", _refused)
    patch.setattr(wdk, "dataset_client", _refused)


def write_wire(into: Path, wire: LookupWire) -> None:
    into.mkdir(parents=True, exist_ok=True)
    (into / FILE).write_text(wire.model_dump_json(indent=1) + "\n")


async def record(into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    tally = Tally()
    set_observer(tally)
    records = RecordTape(get_strategy_api(SITE).get_single_record, [], RECORD_BUDGET)
    with pytest.MonkeyPatch.context() as patch:
        tape_the_reads(patch, records)
        try:
            await resolve_gene_ids_to_records(SITE, RESOLVED)
            await hydrate.hydrate_sparse_gene_results(
                SITE, [GeneResult(gene_id=gene) for gene in HYDRATED]
            )
        finally:
            await close_all_clients()
    if len(tally.wdk) > WDK_BUDGET:
        msg = f"the recording sent {len(tally.wdk)} WDK requests"
        raise RecordingStoppedError(msg)
    write_wire(
        into,
        LookupWire(
            site=SITE, resolved=RESOLVED, hydrated=HYDRATED, records=records.kept
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    asyncio.run(record(parser.parse_args().out))
