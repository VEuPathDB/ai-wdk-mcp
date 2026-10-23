import pytest
from tests._support.control_run_wdk import RunFakeAPI
from tests._support.enrichment_wdk import FakeStrategyAPI
from tests._support.missing_wire import WireReplay
from tests._support.wdk_genes import Datasets
from veupathdb.wdk import StrategyAPI

from veupathdb_mcp.audit import genes, record_reads
from veupathdb_mcp.gene_lookup import wdk

UPLOADERS = (StrategyAPI, RunFakeAPI, FakeStrategyAPI, WireReplay, Datasets)
CLIENT_HOLDERS = (genes, record_reads, wdk)


class DatasetCreatedError(AssertionError):
    pass


class DatasetTrap:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        for uploader in UPLOADERS:
            monkeypatch.setattr(uploader, "create_dataset", self.refuse)
        for holder in CLIENT_HOLDERS:
            monkeypatch.setattr(holder, "dataset_client", self.refuse)

    def refuse(self, *args: object, **kwargs: object) -> None:
        self.calls.append(repr(args))
        raise DatasetCreatedError

    def armed(self) -> bool:
        return all(u.create_dataset == self.refuse for u in UPLOADERS) and all(
            h.dataset_client == self.refuse for h in CLIENT_HOLDERS
        )
