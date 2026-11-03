from __future__ import annotations

import pytest
from veupathdb.domain.parameters import (
    PHYLETIC_EXPRESSION_PARAM,
    ParamSpecNormalized,
    StringValue,
)

from veupathdb_mcp.catalog.wdk_substitution import substituted_params

_WRITTEN = "pfal=0 AND tgon>=1 OR pfal=1 AND tgon>=2"
_RENDERED = "(pfal=0 AND tgon>=1) OR (pfal=1 AND tgon>=2)"


def _substituted(name: str, sent: str, echoed: str) -> list[str]:
    return substituted_params(
        sent={name: StringValue(value=sent)},
        echoed={name: echoed},
        specs={name: ParamSpecNormalized(name=name, param_type="string")},
        values_were_read=True,
    )


def test_the_rendered_spelling_is_not_a_value_wdk_supplied() -> None:
    assert _substituted(PHYLETIC_EXPRESSION_PARAM, _RENDERED, _WRITTEN) == []


@pytest.mark.parametrize(
    ("sent", "echoed"),
    [
        (_RENDERED, "pfal=0 AND tgon>=1 OR pfal=1 AND tgon>=3"),
        (_RENDERED, "pfal=0 AND tgon>=1 OR pber=1 AND tgon>=2"),
        ("pfal=0 AND (tgon>=1 OR pfal>=1)", "pfal=0 AND tgon>=1 OR pfal>=1"),
        (_RENDERED, "pfal=0 AND"),
        (_RENDERED, "(" * 5000),
        (_RENDERED, "pfal>=" + "9" * 5000),
        ("pfal=0 AND", _RENDERED),
    ],
    ids=[
        "count",
        "code",
        "regrouped",
        "echo-grammar",
        "echo-nesting",
        "echo-count",
        "sent-grammar",
    ],
)
def test_a_different_expression_is_a_value_wdk_supplied(sent: str, echoed: str) -> None:
    assert _substituted(PHYLETIC_EXPRESSION_PARAM, sent, echoed) == [
        PHYLETIC_EXPRESSION_PARAM
    ]


def test_two_values_that_do_not_parse_compare_as_written() -> None:
    assert _substituted(PHYLETIC_EXPRESSION_PARAM, "pfal=0 AND", "tgon=1 OR") == [
        PHYLETIC_EXPRESSION_PARAM
    ]
    assert _substituted(PHYLETIC_EXPRESSION_PARAM, "pfal=0 AND", "pfal=0 AND") == []


def test_a_parameter_of_another_name_is_compared_as_written() -> None:
    assert _substituted("text_expression", _RENDERED, _WRITTEN) == ["text_expression"]
