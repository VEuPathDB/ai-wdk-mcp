from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter, ValidationError
from tests._support.wdk_genes import (
    FIXTURES,
    PF3D7,
    PIGA,
    gene_attributes,
    record,
)
from veupathdb import JSONObject
from veupathdb.errors import (
    DataParsingError,
)
from veupathdb.wdk import (
    WDKRecordInstance,
)

from veupathdb_mcp.audit import gene_models
from veupathdb_mcp.audit.genes import (
    OrthologRow,
    ortholog_table,
    orthologs_of,
)


def ortholog_row(gene: str, organism: str, syntenic: str) -> dict[str, object]:
    return {
        "organism": organism,
        "gene": {
            "displayText": f"{gene}.1",
            "url": f"/plasmo.qa/app/record/gene/{gene}",
        },
        "ortho_source_id": f"{gene}.1",
        "ortho_gene_source_id": gene,
        "protein_length": "459",
        "gene_product": "GPI anchor biosynthesis protein",
        "is_syntenic": syntenic,
        "is_reference_strain": "yes",
        "has_comment": "no",
        "source_id": PIGA,
    }


class _Records:
    def __init__(self, tables: dict[str, object]) -> None:
        self._tables = tables
        self.reads: list[tuple[str, list[dict[str, str]], list[str], list[str]]] = []

    async def get_single_record(
        self,
        record_type: str,
        primary_key: list[dict[str, str]],
        *,
        attributes: list[str],
        tables: list[str],
    ) -> WDKRecordInstance:
        self.reads.append((record_type, primary_key, attributes, tables))
        return WDKRecordInstance.model_validate(
            {"id": primary_key, "attributes": {}, "tables": self._tables}
        )


def install_fake_record(
    monkeypatch: pytest.MonkeyPatch, table: list[dict[str, object]] | None
) -> _Records:
    records = _Records({} if table is None else {"Orthologs": table})
    monkeypatch.setattr(gene_models, "get_strategy_api", lambda site_id: records)
    return records


def triple(row: OrthologRow) -> tuple[str, str, bool]:
    return (row.gene, row.organism, row.syntenic)


def located(gene: str, start: int) -> JSONObject:
    attributes: JSONObject = {
        **gene_attributes("300", "No", "protein coding gene"),
        "gene_start_min": str(start),
        "gene_end_max": str(start + 899),
    }
    return record(gene, f"{gene}.1", attributes)


async def test_the_ortholog_table_is_one_gene_record_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = install_fake_record(
        monkeypatch,
        [
            ortholog_row("PmUG01_10043600", "Plasmodium malariae UG01", "yes"),
            ortholog_row("PF3D7_0000100", PF3D7, "no"),
        ],
    )

    table = await ortholog_table("plasmodb", PIGA)

    assert [triple(row) for row in table] == [
        ("PmUG01_10043600", "Plasmodium malariae UG01", True),
        ("PF3D7_0000100", PF3D7, False),
    ]
    assert records.reads == [
        (
            "gene",
            [
                {"name": "source_id", "value": PIGA},
                {"name": "project_id", "value": "PlasmoDB"},
            ],
            [],
            ["Orthologs"],
        )
    ]


async def test_a_group_is_the_table_without_the_gene_and_without_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = install_fake_record(
        monkeypatch,
        [
            ortholog_row("PmUG01_10043600", "Plasmodium malariae UG01", "yes"),
            ortholog_row(PIGA, PF3D7, "yes"),
            ortholog_row("PmUG01_10043600", "Plasmodium malariae UG01", "yes"),
        ],
    )

    group = await orthologs_of("plasmodb", PIGA)

    assert [(r[1][0]["value"], r[3]) for r in records.reads] == [(PIGA, ["Orthologs"])]
    assert group.gene == PIGA
    assert [(m.gene, m.protein_length, m.reference_strain) for m in group.members] == [
        ("PmUG01_10043600", 459, True)
    ]


async def test_a_gene_with_no_orthologs_has_an_empty_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_record(monkeypatch, [])

    assert (await orthologs_of("plasmodb", PIGA)).members == []


async def test_a_gene_record_without_the_ortholog_table_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_record(monkeypatch, None)

    with pytest.raises(DataParsingError, match=f"{PIGA} on plasmodb.*Orthologs"):
        await ortholog_table("plasmodb", PIGA)


@pytest.mark.parametrize(("served", "syntenic"), [("yes", True), ("no", False)])
def test_an_ortholog_row_reads_synteny_from_yes_or_no(
    served: str, syntenic: bool
) -> None:
    row = OrthologRow.model_validate(ortholog_row("X", "O", served))

    assert triple(row) == ("X", "O", syntenic)


@pytest.mark.parametrize(
    "syntenic", ["maybe", "Yes", "true", "1", "", 1, True, False, None]
)
def test_an_ortholog_row_refuses_a_synteny_other_than_yes_or_no(
    syntenic: str | int | bool | None,
) -> None:
    with pytest.raises(ValidationError):
        OrthologRow.model_validate(
            {**ortholog_row("X", "O", "yes"), "is_syntenic": syntenic}
        )


def test_an_ortholog_row_without_its_ortholog_id_is_refused() -> None:
    raw = {**ortholog_row("X", "O", "yes"), "gene": "PLAIN"}
    del raw["ortho_gene_source_id"]

    with pytest.raises(ValidationError):
        OrthologRow.model_validate(raw)


def test_an_ortholog_row_without_an_organism_is_refused() -> None:
    with pytest.raises(ValidationError):
        OrthologRow.model_validate(ortholog_row("X", "", "yes"))


def test_the_recorded_ortholog_table_of_piga_reads_57_syntenic_orthologs() -> None:
    served = json.loads((FIXTURES / "pfal3D7_piga_orthologs.json").read_text())
    rows = TypeAdapter(list[OrthologRow]).validate_python(served)

    assert len(served) == 57
    assert {"ortho_gene_source_id", "is_syntenic", "sort_key"} <= set(served[0])
    assert len({row.organism for row in rows}) == 57
    assert all(row.syntenic for row in rows)
    assert PIGA not in {row.gene for row in rows}
    assert triple(rows[0]) == ("PmUG01_10043600", "Plasmodium malariae UG01", True)
