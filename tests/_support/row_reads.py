import pytest
from pydantic import JsonValue
from veupathdb.errors import WDKError
from veupathdb.wdk import WDKAnswer

from veupathdb_mcp.audit import record_reads
from veupathdb_mcp.audit.genes import LOCUS_TAG, GeneRow, proteins_in, rows_of


class RowReads:
    def __init__(self, rows: list[GeneRow], proteins: dict[str, str]) -> None:
        self.rows = {row.gene: row for row in rows}
        self.proteins = proteins
        self.reads: list[str] = []
        self.protein_reads: list[str] = []

    async def row(self, site_id: str, gene: str) -> GeneRow:
        self.reads.append(gene)
        if gene not in self.rows:
            msg = f"{gene} has no gene record on {site_id}"
            raise WDKError(msg, status=404)
        return self.rows[gene]

    async def protein(self, site_id: str, gene: str) -> str | None:
        self.protein_reads.append(gene)
        return self.proteins.get(gene)


def recorded_answers(bodies: list[JsonValue]) -> list[WDKAnswer]:
    return [WDKAnswer.model_validate(body) for body in bodies]


def serve_recorded_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[JsonValue],
    proteins: list[JsonValue] | None = None,
    recorded: dict[str, str] | None = None,
) -> RowReads:
    served = RowReads(
        [
            row
            for answer in recorded_answers(rows)
            for row in rows_of(answer, LOCUS_TAG)
        ],
        proteins_in(recorded_answers(proteins or [])) | (recorded or {}),
    )
    monkeypatch.setattr(record_reads, "_row", served.row)
    monkeypatch.setattr(record_reads, "_protein", served.protein)
    return served


def serve_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[GeneRow],
    proteins: dict[str, str] | None = None,
) -> RowReads:
    served = RowReads(rows, proteins or {})
    monkeypatch.setattr(record_reads, "_row", served.row)
    monkeypatch.setattr(record_reads, "_protein", served.protein)
    return served
