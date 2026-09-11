"""Contextualizing a search's parameters is an enrichment, not a precondition.

Six call sites asked WDK for "this search's parameters under this context" and
each invented its own failure policy: two had none at all, the rest caught four
different exception types and recovered four different ways. The two with none
are where the bugs landed.

Proven on live PlasmoDB, ``GenesByOrthologPattern``:

    refresh, organism = ["Plasmodium falciparum 3D7"] + profile_pattern -> 500
    RUN,     same values, gold parameter set                            -> 200, a non-empty result

WDK returns 500 on the endpoint that narrows a child's vocabulary, for a value
it accepts and executes on the endpoint that runs the search. Nothing we send is
invalid. Abandoning the criterion there cost the entire multi-criterion strategy.

The contextualized view narrows vocabularies. Losing it costs vocabulary
precision; it must never cost the search.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from veupathdb.domain.strategy import StepValidation
from veupathdb.errors import VEuPathDBError, WDKError
from veupathdb.wdk import WDKParameter, WDKSearch, WDKSearchResponse, WDKStringParam

from veupathdb_mcp.catalog.search_context import (
    context_for_metadata_read,
    get_search_params_under_context,
)


def _param(
    name: str,
    *,
    visible: bool = True,
    allow_empty: bool = False,
    default: str | None = None,
) -> WDKParameter:
    return WDKStringParam(
        name=name,
        display_name=name,
        is_visible=visible,
        allow_empty_value=allow_empty,
        initial_display_value=default,
    )


def _response(*parameters: WDKParameter) -> WDKSearchResponse:
    return WDKSearchResponse(
        search_data=WDKSearch(
            url_segment="S",
            param_names=[p.name for p in parameters],
            parameters=list(parameters),
        ),
        validation=StepValidation(level="NONE", is_valid=False),
    )


def _client(*, contextual: Any, plain: Any) -> Any:
    client = MagicMock()
    client.get_search_details_with_params = (
        AsyncMock(side_effect=contextual)
        if isinstance(contextual, BaseException)
        else AsyncMock(return_value=contextual)
    )
    client.get_search_details = (
        AsyncMock(side_effect=plain)
        if isinstance(plain, BaseException)
        else AsyncMock(return_value=plain)
    )
    return client


class TestContextIsUsedWhenItWorks:
    @pytest.mark.asyncio
    async def test_returns_the_contextualized_view(self) -> None:
        client = _client(
            contextual=_response(_param("narrowed")), plain=_response(_param("static"))
        )

        result = await get_search_params_under_context(
            client, "transcript", "GenesByOrthologPattern", {"organism": "[]"}
        )

        assert result.search_data.param_names == ["narrowed"]

    @pytest.mark.asyncio
    async def test_passes_the_context_through(self) -> None:
        client = _client(
            contextual=_response(_param("narrowed")),
            plain=_response(_param("profile_pattern", visible=False)),
        )

        await get_search_params_under_context(
            client, "transcript", "S", {"profile_pattern": "%pfal:Y%"}
        )

        kwargs = client.get_search_details_with_params.await_args.kwargs
        assert kwargs["context"] == {"profile_pattern": "%pfal:Y%"}

    @pytest.mark.asyncio
    async def test_an_empty_context_skips_the_contextual_call(self) -> None:
        # Nothing to narrow by; the POST would only cost a round trip.
        client = _client(
            contextual=_response(_param("narrowed")), plain=_response(_param("static"))
        )

        result = await get_search_params_under_context(client, "transcript", "S", {})

        assert result.search_data.param_names == ["static"]
        client.get_search_details_with_params.assert_not_awaited()


class TestContextFailureDegrades:
    @pytest.mark.asyncio
    async def test_a_5xx_falls_back_to_the_static_view(self) -> None:
        client = _client(
            contextual=WDKError("500 Internal Error", status=500),
            plain=_response(_param("static")),
        )

        result = await get_search_params_under_context(
            client, "transcript", "GenesByOrthologPattern", {"organism": "[]"}
        )

        assert result.search_data.param_names == ["static"]

    @pytest.mark.asyncio
    async def test_both_endpoints_are_tried_when_wdk_cannot_contextualize(self) -> None:
        client = _client(
            contextual=WDKError("boom", status=500), plain=_response(_param("static"))
        )

        await get_search_params_under_context(client, "transcript", "S", {"a": "b"})

        assert client.get_search_details_with_params.await_count == 1
        assert client.get_search_details.await_count == 1

    @pytest.mark.asyncio
    async def test_still_raises_when_the_search_itself_is_unreachable(self) -> None:
        # Both endpoints down is a real outage, not a narrowing we can skip.
        client = _client(
            contextual=WDKError("boom", status=500),
            plain=WDKError("also boom", status=500),
        )

        with pytest.raises(VEuPathDBError):
            await get_search_params_under_context(client, "transcript", "S", {"a": "b"})


class TestHiddenParamsJoinTheRead:
    """A hidden param carries a value the caller cannot state, so the read sends it.

    ``GenesByOrthologPattern`` answers 500 to a contextual read that omits
    ``phyletic_indent_map`` or ``phyletic_term_map``, and WDK judges the shape it
    is given, so a hidden required param it does not receive comes back empty.
    """

    def test_a_hidden_allow_empty_default_is_added(self) -> None:
        published = [
            _param("phyletic_term_map", visible=False, allow_empty=True, default="[]")
        ]

        assert context_for_metadata_read({"organism": "[]"}, published) == {
            "organism": "[]",
            "phyletic_term_map": "[]",
        }

    def test_a_visible_allow_empty_default_is_not_added(self) -> None:
        published = [
            _param("included_species", visible=True, allow_empty=True, default="")
        ]

        assert context_for_metadata_read({"organism": "[]"}, published) == {
            "organism": "[]"
        }

    def test_a_hidden_required_param_is_added(self) -> None:
        """WDK judges the shape it receives, so an omitted one reads as empty.

        The run path still decides the value through
        ``fill_hidden_required_defaults``; this is the metadata read.
        """
        published = [
            _param("document_type", visible=False, allow_empty=False, default="gene")
        ]

        assert context_for_metadata_read({"text_expression": "kinase"}, published) == {
            "text_expression": "kinase",
            "document_type": "gene",
        }

    def test_a_hidden_param_without_a_published_default_is_not_added(self) -> None:
        published = [
            _param("phyletic_term_map", visible=False, allow_empty=True, default=None)
        ]

        assert context_for_metadata_read({}, published) == {}

    def test_the_caller_keeps_its_own_value(self) -> None:
        published = [
            _param("phyletic_term_map", visible=False, allow_empty=True, default="[]")
        ]

        assert context_for_metadata_read({"phyletic_term_map": '["x"]'}, published) == {
            "phyletic_term_map": '["x"]'
        }

    @pytest.mark.asyncio
    async def test_the_contextual_read_sends_them(self) -> None:
        published = _response(
            _param("organism"),
            _param(
                "profile_pattern", visible=False, allow_empty=False, default="hsap=1T"
            ),
            _param(
                "phyletic_indent_map", visible=False, allow_empty=True, default="[]"
            ),
            _param("phyletic_term_map", visible=False, allow_empty=True, default="[]"),
        )
        client = _client(contextual=_response(_param("narrowed")), plain=published)

        await get_search_params_under_context(
            client,
            "transcript",
            "GenesByOrthologPattern",
            {"organism": '["Plasmodium falciparum 3D7"]'},
        )

        kwargs = client.get_search_details_with_params.await_args.kwargs
        assert kwargs["context"] == {
            "organism": '["Plasmodium falciparum 3D7"]',
            "profile_pattern": "hsap=1T",
            "phyletic_indent_map": "[]",
            "phyletic_term_map": "[]",
        }
