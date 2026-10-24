from __future__ import annotations

from pydantic import BaseModel

from veupathdb_mcp import SENTENCE_FORMAT, SHARE_FORMAT
from veupathdb_mcp.audit.introns import IntronAudit, IntronDepth, IntronJudgement
from veupathdb_mcp.audit.introns_orthologs import OrthologSupport
from veupathdb_mcp.audit.missing import Located
from veupathdb_mcp.audit.rates import RateBounds


def _shares(model: type[BaseModel]) -> dict[str, object]:
    properties = model.model_json_schema(mode="serialization")["properties"]
    return {
        name: {key: value for key, value in schema.items() if key != "title"}
        for name, schema in properties.items()
        if schema.get("format") == SHARE_FORMAT
    }


def test_each_served_share_carries_the_share_format() -> None:
    assert {
        m.__name__: sorted(_shares(m)) for m in (IntronDepth, Located, RateBounds)
    } == {
        "IntronDepth": ["coveredShare"],
        "Located": ["share"],
        "RateBounds": ["ceiling", "floor", "high", "low", "rate"],
    }


def test_a_bounded_share_keeps_its_bounds() -> None:
    assert _shares(IntronDepth)["coveredShare"] == {
        "format": "share",
        "maximum": 1,
        "minimum": 0,
        "type": "number",
    }


def test_a_depth_ratio_that_can_pass_one_is_no_share() -> None:
    """depthShare is intron depth over exon depth, so a retained intron read
    deeper than its exons passes 1; shown as a share it would read as 140%."""
    depth = IntronDepth(
        intron_median_depth=14.0, exon_median_depth=10.0, covered_share=1.0, track="t"
    )

    assert depth.depth_share == 1.4
    assert (
        "format"
        not in IntronDepth.model_json_schema(mode="serialization")["properties"][
            "depthShare"
        ]
    )


def _sentences(model: type[BaseModel]) -> list[str]:
    properties = model.model_json_schema(mode="serialization")["properties"]
    return sorted(
        name
        for name, schema in properties.items()
        if any(
            branch.get("format") == SENTENCE_FORMAT
            for branch in [schema, *schema.get("anyOf", [])]
        )
    )


def test_each_served_free_text_carries_the_sentence_format() -> None:
    models = (IntronAudit, IntronJudgement, OrthologSupport)

    assert {m.__name__: _sentences(m) for m in models} == {
        "IntronAudit": ["correctionReason", "reason"],
        "IntronJudgement": ["reason"],
        "OrthologSupport": ["reason"],
    }
