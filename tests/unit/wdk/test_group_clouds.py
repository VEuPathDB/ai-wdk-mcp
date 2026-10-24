import pytest
from pydantic import JsonValue
from tests._support.group_cloud_site import (
    CloudSite,
    cloud_body,
    cloud_counts,
    recorded,
    recorded_tree,
    serve_clouds,
    total_of,
)
from veupathdb.errors import DataParsingError

from veupathdb_mcp.wdk import (
    GroupCloudCappedError,
    GroupCloudSumError,
    GroupTagError,
    read_group_proteins,
)

TGON = frozenset({"tgon"})


def _unused(expression: str) -> int:
    raise AssertionError(expression)


def _site(monkeypatch: pytest.MonkeyPatch, cloud: JsonValue, records: int) -> CloudSite:
    return serve_clouds(
        monkeypatch,
        CloudSite({TGON: cloud}, {TGON: records}, _unused),
        recorded_tree(),
    )


async def test_one_genome_reads_its_proteins_per_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = _site(monkeypatch, recorded("r02_tgon_groupcloud"), total_of("r02_tgon_std"))

    read = await read_group_proteins("orthomcl", ["tgon"])

    assert (len(read.proteins), read.records) == (6038, 8140)
    assert sum(read.proteins.values()) == 8140
    assert read.proteins["OG8_0000011"] == 32
    assert site.sent == [("cloud", '["tgon"]'), ("records", '["tgon"]')]


async def test_a_word_that_is_no_group_id_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts = cloud_counts("r02_tgon_groupcloud")
    counts["PF3D7_0100100"] = counts.pop("OG8_0000011")
    _site(monkeypatch, cloud_body(counts), total_of("r02_tgon_std"))

    with pytest.raises(GroupTagError) as refused:
        await read_group_proteins("orthomcl", ["tgon"])

    assert refused.value.tags == ("PF3D7_0100100",)


async def test_counts_that_do_not_sum_to_the_records_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch, recorded("r02_tgon_groupcloud"), total_of("r02_tgon_std") + 1)

    with pytest.raises(GroupCloudSumError) as refused:
        await read_group_proteins("orthomcl", ["tgon"])

    assert (refused.value.total, refused.value.records) == (8140, 8141)


async def test_counts_above_the_records_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch, recorded("r02_tgon_groupcloud"), total_of("r02_tgon_std") - 1)

    with pytest.raises(GroupCloudSumError) as refused:
        await read_group_proteins("orthomcl", ["tgon"])

    assert (refused.value.total, refused.value.records) == (8140, 8139)


async def test_a_word_named_twice_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"tags": [{"word": "OG8_0000011", "count": 1}] * 2}
    _site(monkeypatch, body, 2)

    with pytest.raises(GroupTagError) as refused:
        await read_group_proteins("orthomcl", ["tgon"])

    assert refused.value.tags == ("OG8_0000011",)


async def test_a_cloud_of_another_shape_is_a_parsing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch, {"tags": [{"word": "OG8_0000011"}]}, 1)

    with pytest.raises(DataParsingError) as refused:
        await read_group_proteins("orthomcl", ["tgon"])

    assert type(refused.value) is DataParsingError


async def test_the_word_cap_sentinel_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _site(monkeypatch, {"tags": [{"word": "Too many words", "count": 1}]}, 1)

    with pytest.raises(GroupCloudCappedError) as refused:
        await read_group_proteins("orthomcl", ["tgon"])

    assert refused.value.genomes == ("tgon",)
    assert "cap of 10000 groups" in (refused.value.detail or "")
