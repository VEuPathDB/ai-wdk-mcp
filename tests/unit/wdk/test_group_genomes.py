"""A group record's TaxonCounts table read as proteins per genome."""

from __future__ import annotations

import pytest
from veupathdb.errors import DataParsingError
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKAnswer, WDKRecordInstance

from veupathdb_mcp.wdk import GROUP_GENOME_TABLE, group_genome_counts


def _recorded() -> dict[str, dict[str, int]]:
    answer = WDKAnswer.model_validate(load_recorded("orthomcl_group_taxon_counts").body)
    return {
        counts.group: counts.proteins for counts in group_genome_counts(answer.records)
    }


def test_the_table_is_taxon_counts() -> None:
    assert GROUP_GENOME_TABLE == "TaxonCounts"


def test_a_single_copy_group_holds_one_protein_in_each_genome() -> None:
    proteins = _recorded()["OG8_0031041"]
    assert (len(proteins), set(proteins.values())) == (139, {1})


def test_a_large_group_counts_its_proteins_per_genome() -> None:
    proteins = _recorded()["OG8_0003303"]
    several = [genome for genome, count in proteins.items() if count > 1]
    assert (len(proteins), sum(proteins.values()), len(several)) == (736, 1068, 180)


def test_a_genome_is_named_by_its_abbreviation() -> None:
    proteins = _recorded()["OG8_0003303"]
    assert (proteins["anig"], proteins["nbom"]) == (1, 1)


def test_a_record_without_the_table_is_refused_naming_the_group() -> None:
    record = WDKRecordInstance.model_validate(
        {"id": [{"name": "group_name", "value": "OG8_0031041"}], "tables": {}}
    )

    with pytest.raises(DataParsingError, match=r"OG8_0031041.*TaxonCounts"):
        group_genome_counts([record])


def _record(rows: list[dict[str, str | None]]) -> WDKRecordInstance:
    return WDKRecordInstance.model_validate(
        {
            "id": [{"name": "group_name", "value": "OG8_0003303"}],
            "tables": {"TaxonCounts": rows},
        }
    )


@pytest.mark.parametrize("count", ["0", None])
def test_an_unreadable_row_is_a_parsing_error_naming_the_group(
    count: str | None,
) -> None:
    record = _record([{"abbrev": "pfal", "count": count}])

    with pytest.raises(DataParsingError, match=r"OG8_0003303.*TaxonCounts"):
        group_genome_counts([record])


def test_a_genome_named_twice_is_refused() -> None:
    record = _record(
        [{"abbrev": "pfal", "count": "2"}, {"abbrev": "pfal", "count": "3"}]
    )

    with pytest.raises(DataParsingError, match=r"OG8_0003303.*pfal"):
        group_genome_counts([record])


def test_a_group_with_no_genome_is_refused() -> None:
    with pytest.raises(DataParsingError, match=r"OG8_0003303.*no genome"):
        group_genome_counts([_record([])])


def test_a_record_without_a_group_name_is_refused() -> None:
    record = WDKRecordInstance.model_validate(
        {
            "id": [{"name": "source_id", "value": "OG8_0031041"}],
            "tables": {"TaxonCounts": [{"abbrev": "pfal", "count": "1"}]},
        }
    )

    with pytest.raises(DataParsingError, match="group_name"):
        group_genome_counts([record])
