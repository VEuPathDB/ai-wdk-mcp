from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence

import pydantic
from pydantic import ConfigDict, Field, JsonValue
from veupathdb.errors import DataParsingError, ValidationError
from veupathdb.model import CamelModel
from veupathdb.wdk import (
    ColumnNotCountableError,
    WDKSearchConfig,
    WDKWordCounts,
    get_wdk_client,
)

from veupathdb_mcp.catalog.group_counts import COUNT_ONLY
from veupathdb_mcp.catalog.group_ids import is_group_id

SEQUENCE_RECORD_TYPE = "sequence"
TAXON_SEARCH = "ByTaxonomy"
TAXON_PARAM = "taxon_type_ahead"
GROUP_CLOUD_REPORTER = "group_link-wordCloud"
MAX_CLOUD_WORDS = 10_000
_SHOWN = 5


class GroupCloudCappedError(ValidationError):
    def __init__(self, genomes: Sequence[str]) -> None:
        self.genomes = tuple(genomes)
        super().__init__(
            title="The group cloud stopped at its word cap",
            detail=(
                f"The group word cloud of {len(self.genomes)} genomes stopped at the "
                f"reporter's cap of {MAX_CLOUD_WORDS} groups and returned no counts."
            ),
        )


class GroupTagError(DataParsingError):
    def __init__(self, tags: Sequence[str]) -> None:
        self.tags = tuple(tags)
        super().__init__(
            f"The group word cloud names {len(self.tags)} words that are no "
            f"OrthoMCL group id, such as {list(self.tags[:_SHOWN])}."
        )


class GroupCloudSumError(DataParsingError):
    def __init__(self, total: int, records: int) -> None:
        self.total = total
        self.records = records
        super().__init__(
            f"The group word cloud counts {total} proteins and the search holds "
            f"{records}, so its counts are not proteins per group."
        )


class GroupProteins(CamelModel):
    model_config = ConfigDict(frozen=True)

    genomes: tuple[str, ...] = Field(min_length=1)
    proteins: dict[str, int]
    records: int = Field(ge=0)

    def counts(self) -> Counter[str]:
        return Counter(self.proteins)


def taxon_config(genomes: Sequence[str]) -> WDKSearchConfig:
    return WDKSearchConfig(parameters={TAXON_PARAM: json.dumps(list(genomes))})


def _cloud_path() -> str:
    return (
        f"/record-types/{SEQUENCE_RECORD_TYPE}/searches/{TAXON_SEARCH}"
        f"/reports/{GROUP_CLOUD_REPORTER}"
    )


def _cloud(raw: JsonValue, genomes: Sequence[str]) -> WDKWordCounts:
    try:
        return WDKWordCounts.model_validate(raw)
    except pydantic.ValidationError as refused:
        if any(error["loc"] == () for error in refused.errors()):
            raise GroupCloudCappedError(genomes) from refused
        msg = f"Unexpected {GROUP_CLOUD_REPORTER} report: {refused}"
        raise DataParsingError(msg) from refused


def _counted(cloud: WDKWordCounts, records: int) -> dict[str, int]:
    words = [tag.word for tag in cloud.tags]
    unknown = [word for word in words if not is_group_id(word)]
    if unknown:
        raise GroupTagError(unknown)
    repeated = sorted(word for word, times in Counter(words).items() if times > 1)
    if repeated:
        raise GroupTagError(repeated)
    try:
        return cloud.record_counts(records)
    except ColumnNotCountableError as unequal:
        raise GroupCloudSumError(cloud.total, records) from unequal


async def read_group_proteins(
    site_id: str, genomes: Sequence[str], *, budget_seconds: float | None = None
) -> GroupProteins:
    client = get_wdk_client(site_id)
    config = taxon_config(genomes)
    raw = await client.post(
        _cloud_path(),
        json={
            "searchConfig": config.model_dump(by_alias=True, exclude_defaults=True),
            "reportConfig": {},
        },
        budget_seconds=budget_seconds,
    )
    cloud = _cloud(raw, genomes)
    answer = await client.run_search_report(
        SEQUENCE_RECORD_TYPE,
        TAXON_SEARCH,
        config,
        COUNT_ONLY,
        budget_seconds=budget_seconds,
    )
    records = answer.meta.records_returned()
    return GroupProteins(
        genomes=tuple(genomes), proteins=_counted(cloud, records), records=records
    )
