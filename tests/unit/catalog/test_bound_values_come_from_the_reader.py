from __future__ import annotations

from typing import Any, cast

import pytest
from veupathdb.domain.parameters import MultiPickValue, ParamValue

from veupathdb_mcp.catalog import NOTHING_READ, BoundValues

_RAW: dict[str, ParamValue] = {"organism": MultiPickValue(values=["Pf3D7"])}


def test_a_reading_cannot_be_built_without_the_reader() -> None:
    with pytest.raises(TypeError, match="only read_under_parents binds values"):
        BoundValues(_RAW, cast("Any", None))


def test_the_empty_reading_cannot_change() -> None:
    with pytest.raises(TypeError):
        cast("Any", NOTHING_READ)._values["organism"] = _RAW["organism"]

    assert dict(NOTHING_READ) == {}
