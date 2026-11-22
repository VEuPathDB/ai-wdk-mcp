from __future__ import annotations

import pytest
from pydantic import JsonValue
from tests._support.filter_reads import FilterReadsDouble
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import StatedValuesError

from veupathdb_mcp.catalog.param_dag import (
    ParameterInfo,
    ResolvedParams,
    resolve_params_with_intent,
)
from veupathdb_mcp.catalog.param_intent import ParamIntent, Provenance

from .conftest import fetcher, param_info

_RANGE = "period_range"


def _range(default: str = '{"min":"20","max":"28"}') -> ParameterInfo:
    return param_info(_RANGE, "number-range", default=default)


async def _resolve(
    *infos: ParameterInfo, stated: dict[str, JsonValue] | None = None
) -> ResolvedParams:
    return await resolve_params_with_intent(
        filter_reads=FilterReadsDouble(),
        fetch_at=fetcher(*infos),
        search=SearchContext("plasmodb", "transcript", "GenesByRhythm"),
        intent=ParamIntent(text="genes with a rhythm"),
        stated=stated or {},
        about=None,
    )


async def test_a_range_with_no_stated_value_takes_the_site_default() -> None:
    resolved = await _resolve(_range())

    assert resolved.params[_RANGE].to_decoded() == {"min": 20.0, "max": 28.0}
    assert resolved.provenance[_RANGE] is Provenance.DEFAULTED
    assert resolved.open_slots == []


async def test_a_date_range_with_no_stated_value_takes_the_site_default() -> None:
    resolved = await _resolve(
        param_info(
            "dates", "date-range", default='{"min":"2020-01-01","max":"2020-12-31"}'
        )
    )

    assert resolved.params["dates"].to_decoded() == {
        "min": "2020-01-01",
        "max": "2020-12-31",
    }


async def test_a_range_stated_as_its_object_binds() -> None:
    resolved = await _resolve(_range(), stated={_RANGE: {"min": 22, "max": 26}})

    assert resolved.params[_RANGE].to_decoded() == {"min": 22.0, "max": 26.0}
    assert resolved.provenance[_RANGE] is Provenance.STATED


async def test_a_required_range_with_no_default_is_an_open_slot() -> None:
    resolved = await _resolve(_range(default=""))

    assert [slot.param_name for slot in resolved.open_slots] == [_RANGE]


@pytest.mark.parametrize(
    "stated", ["22-26", "22..26", [22, 26], '{"min": 22, "max": 26}']
)
async def test_a_stated_value_the_kind_cannot_read_is_refused(
    stated: JsonValue,
) -> None:
    with pytest.raises(StatedValuesError) as refused:
        await _resolve(_range(), stated={_RANGE: stated})

    assert [(f.name, f.read) for f in refused.value.faults] == [(_RANGE, stated)]
    assert _RANGE in str(refused.value.detail)
