from __future__ import annotations

import pytest
from veupathdb.errors import WDKError
from veupathdb.wdk import WDKAnswer, WDKAnswerMeta, WDKRecordInstance

from veupathdb_mcp.wdk import step_preview
from veupathdb_mcp.wdk.step_preview import step_sample_records

_GENE_ATTRS = ["gene_product", "gene_name", "organism"]
_ATTRIBUTE_MISSING = "attribute 'gene_product' not found"
_NOT_IN_A_STRATEGY = "step 5 is not part of a strategy"


def _answer(records: list[WDKRecordInstance], attributes: list[str]) -> WDKAnswer:
    return WDKAnswer(
        meta=WDKAnswerMeta(
            total_count=len(records),
            record_class_name="transcript",
            attributes=attributes,
        ),
        records=records,
    )


class _FakeStrategyAPI:
    """``get_step_answer`` succeeds only WITHOUT attributes - simulating a
    record class that rejects the gene attributes."""

    def __init__(self, records: list[WDKRecordInstance] | None = None) -> None:
        self.calls: list[list[str] | None] = []
        self._records = records

    async def get_step_answer(
        self,
        step_id: int,
        attributes: list[str] | None = None,
        pagination: dict[str, int] | None = None,
        user_id: str | None = None,
    ) -> WDKAnswer:
        del step_id, pagination, user_id
        self.calls.append(attributes)
        if attributes and self._records is None:
            raise WDKError(_ATTRIBUTE_MISSING)
        if self._records is not None:
            return _answer(self._records, attributes or [])
        return _answer([WDKRecordInstance(display_name="x1")], [])


def _bind(monkeypatch: pytest.MonkeyPatch, api: _FakeStrategyAPI) -> None:
    monkeypatch.setattr(step_preview, "get_strategy_api", lambda site_id: api)


async def test_html_is_stripped_from_the_attribute_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WDK returns organism wrapped in <i>...</i>; the read must surface a clean
    # value alongside the id + product name.
    api = _FakeStrategyAPI(
        [
            WDKRecordInstance(
                display_name="PF3D7_0610600",
                attributes={
                    "gene_product": "calcium-dependent protein kinase 2",
                    "gene_name": "CDPK2",
                    "organism": "<i>Plasmodium falciparum 3D7</i>",
                },
            ),
        ],
    )
    _bind(monkeypatch, api)

    result = await step_sample_records(
        "plasmodb",
        123,
        limit=5,
        attributes=_GENE_ATTRS,
    )

    assert result.step_id == 123
    assert result.total_count == 1
    assert result.attributes == _GENE_ATTRS
    assert result.records[0] == {
        "id": "PF3D7_0610600",
        "gene_product": "calcium-dependent protein kinase 2",
        "gene_name": "CDPK2",
        "organism": "Plasmodium falciparum 3D7",
    }


async def test_a_rejected_attribute_set_falls_back_to_an_id_only_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeStrategyAPI()
    _bind(monkeypatch, api)

    result = await step_sample_records(
        "plasmodb",
        5,
        limit=3,
        attributes=_GENE_ATTRS,
    )

    assert api.calls == [_GENE_ATTRS, None]  # tried enriched, then id-only
    assert result.records == [{"id": "x1"}]


async def test_a_refused_id_only_read_reaches_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Refusing(_FakeStrategyAPI):
        async def get_step_answer(
            self,
            step_id: int,
            attributes: list[str] | None = None,
            pagination: dict[str, int] | None = None,
            user_id: str | None = None,
        ) -> WDKAnswer:
            del step_id, attributes, pagination, user_id
            raise WDKError(_NOT_IN_A_STRATEGY)

    _bind(monkeypatch, _Refusing())

    with pytest.raises(WDKError, match="not part of a strategy"):
        await step_sample_records("plasmodb", 5, limit=3, attributes=_GENE_ATTRS)
