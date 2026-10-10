from __future__ import annotations

import pytest
from veupathdb.domain.parameters.values import DateRangeValue, NumberRangeValue

from veupathdb_mcp.catalog import UnreadableValueError
from veupathdb_mcp.catalog.param_dag import (
    OverrideMap,
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
    *infos: ParameterInfo, overrides: OverrideMap | None = None
) -> ResolvedParams:
    return await resolve_params_with_intent(
        fetch_at=fetcher(*infos),
        intent=ParamIntent(text="genes with a rhythm"),
        overrides=overrides,
    )


async def test_a_range_with_no_stated_value_takes_the_site_default() -> None:
    resolved = await _resolve(_range())

    assert resolved.params[_RANGE] == NumberRangeValue(min=20.0, max=28.0)
    assert resolved.provenance[_RANGE] is Provenance.DEFAULTED
    assert resolved.open_slots == []


async def test_a_date_range_with_no_stated_value_takes_the_site_default() -> None:
    resolved = await _resolve(
        param_info(
            "dates", "date-range", default='{"min":"2020-01-01","max":"2020-12-31"}'
        )
    )

    assert resolved.params["dates"] == DateRangeValue(
        min="2020-01-01", max="2020-12-31"
    )


@pytest.mark.parametrize(
    "stated", ['{"min":"22","max":"26"}', '{"min": 22, "max": 26}']
)
async def test_a_range_stated_as_its_json_text_binds(stated: str) -> None:
    resolved = await _resolve(_range(), overrides={_RANGE: stated})

    assert resolved.params[_RANGE] == NumberRangeValue(min=22.0, max=26.0)
    assert resolved.provenance[_RANGE] is Provenance.STATED


async def test_a_required_range_with_no_default_is_an_open_slot() -> None:
    resolved = await _resolve(_range(default=""))

    assert [slot.param_name for slot in resolved.open_slots] == [_RANGE]


@pytest.mark.parametrize("stated", ["22-26", "22..26", "[22, 26]"])
async def test_a_stated_value_the_kind_cannot_read_is_refused(stated: str) -> None:
    with pytest.raises(UnreadableValueError) as refused:
        await _resolve(_range(), overrides={_RANGE: stated})

    assert refused.value.param_name == _RANGE
    assert refused.value.value == stated
    assert _RANGE in str(refused.value.detail)
