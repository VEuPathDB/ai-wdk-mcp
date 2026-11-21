"""The parameter DAG walk: filter params, dependent chains, unknown names, and
the fetcher that reads WDK."""

from __future__ import annotations

import pytest
from pydantic import JsonValue
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    FilterFacet,
    FilterStatementError,
    FilterValue,
    MultiPickValue,
    NumberValue,
    SinglePickValue,
    StatedValuesError,
    VocabOption,
)
from veupathdb.errors import ValidationError, VEuPathDBErrorCode
from veupathdb.wdk import WDKParameter, WDKSearchResponse, WDKStringParam

from veupathdb_mcp.catalog import param_dag
from veupathdb_mcp.catalog.param_dag import (
    ParameterInfo,
    ParamFetcher,
    ResolvedParams,
    UnknownParameterError,
    resolve_params_with_intent,
)
from veupathdb_mcp.catalog.param_intent import ParamIntent

from .conftest import (
    bound,
    declaring,
    facet,
    fetcher,
    param_info,
    vocab,
    wdk_search_response,
)

Clauses = list[tuple[str, str, bool, list[str]]]


async def _walk(
    *,
    fetch_at: ParamFetcher,
    stated: dict[str, JsonValue] | None = None,
    intent: ParamIntent | None = None,
) -> ResolvedParams:
    return await resolve_params_with_intent(
        fetch_at=fetch_at,
        search_name="GenesByRNASeqEvidence",
        intent=intent or ParamIntent(),
        stated=stated or {},
    )


_SAMPLE_FACETS = [
    facet("Sample type", members=("specimen from organism", "culture", "blood")),
    facet("Country", members=("India",)),
]


def _filter(name: str, fields: list[FilterFacet]) -> ParameterInfo:
    return param_info(name, "filter", filter_fields=fields)


def _strain_meta() -> ParamFetcher:
    return fetcher(_filter("ngsSnp_strain_meta", _SAMPLE_FACETS))


class TestFilterParams:
    async def test_a_filter_param_defaults_to_include_all(self) -> None:
        """The WDK default for a filter param is the empty filter set, and it
        resolves rather than opening a slot."""
        resolved = await _walk(
            fetch_at=_strain_meta(),
        )

        value = resolved.params["ngsSnp_strain_meta"]
        assert isinstance(value, FilterValue)
        assert value.filters == []
        assert value.to_wire() == '{"filters": []}'
        assert resolved.unresolved_required == []
        assert resolved.open_slots == []

    async def test_a_statement_builds_the_clause_the_ontology_types(self) -> None:
        resolved = await _walk(
            fetch_at=_strain_meta(),
            stated={
                "ngsSnp_strain_meta": [
                    {"field": "Sample type", "value": ["culture", "blood"]}
                ]
            },
        )

        value = resolved.params["ngsSnp_strain_meta"]
        assert isinstance(value, FilterValue)
        assert [(c.field, c.type, c.is_range, c.value) for c in value.filters] == [
            ("Sample type", "string", False, ["culture", "blood"])
        ]

    @pytest.mark.parametrize(
        "stated",
        [
            "Sample type=culture,blood",
            '{"filters": []}',
            "All field isolates",
            [],
            {"filters": [{"field": "Sample type", "value": ["culture"]}]},
        ],
    )
    async def test_a_value_that_is_no_list_of_statements_is_refused(
        self, stated: JsonValue
    ) -> None:
        with pytest.raises(StatedValuesError) as refused:
            await _walk(fetch_at=_strain_meta(), stated={"ngsSnp_strain_meta": stated})

        assert [fault.name for fault in refused.value.faults] == ["ngsSnp_strain_meta"]

    async def test_a_member_the_facet_lacks_is_refused(self) -> None:
        with pytest.raises(FilterStatementError, match="has no member"):
            await _walk(
                fetch_at=_strain_meta(),
                stated={
                    "ngsSnp_strain_meta": [{"field": "Sample type", "value": ["soil"]}]
                },
            )


_LOFFLER_FACETS = [facet("PCR result", members=("Negative", "Positive"))]


def _loffler() -> ParamFetcher:
    return fetcher(
        *(
            param_info(
                f"{side}_samples_filter_metadata_loffler",
                "filter",
                filter_fields=_LOFFLER_FACETS,
            )
            for side in ("ref", "comp")
        )
    )


class TestFilterPairs:
    async def test_a_ref_comp_pair_surfaces_instead_of_all_vs_all(self) -> None:
        # A reference and comparison filter pair must not both take the empty
        # filter, because that compares a set against itself.
        resolved = await _walk(
            fetch_at=_loffler(),
        )

        assert "ref_samples_filter_metadata_loffler" not in resolved.params
        assert "comp_samples_filter_metadata_loffler" not in resolved.params
        assert set(resolved.unresolved_required) == {
            "ref_samples_filter_metadata_loffler",
            "comp_samples_filter_metadata_loffler",
        }

    async def test_a_ref_comp_pair_resolves_to_distinct_groups_when_overridden(
        self,
    ) -> None:
        resolved = await _walk(
            fetch_at=_loffler(),
            stated={
                "ref_samples_filter_metadata_loffler": [
                    {"field": "PCR result", "value": ["Negative"]}
                ],
                "comp_samples_filter_metadata_loffler": [
                    {"field": "PCR result", "value": ["Positive"]}
                ],
            },
        )

        ref = resolved.params["ref_samples_filter_metadata_loffler"]
        comp = resolved.params["comp_samples_filter_metadata_loffler"]
        assert isinstance(ref, FilterValue)
        assert isinstance(comp, FilterValue)
        assert ref.filters[0].value == ["Negative"]
        assert comp.filters[0].value == ["Positive"]
        assert resolved.unresolved_required == []


class TestTheDependentChain:
    async def test_the_tiers_resolve_and_a_dependent_appears(self) -> None:
        async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
            params = [
                param_info("organism", "multi-pick-vocabulary"),
                param_info("strand", allowed=vocab("sense")),
                param_info("min_tm", "number", default="1"),
                param_info("profileset", allowed=vocab("ds_x")),
            ]
            if "profileset" in context:
                params.append(
                    param_info(
                        "samples",
                        "multi-pick-vocabulary",
                        allowed=vocab("s1", "s2"),
                        depends_on=["profileset"],
                    )
                )
            return params

        resolved = await _walk(
            fetch_at=declaring(fetch_at),
            stated={"organism": ["Plasmodium falciparum 3D7"]},
        )

        assert isinstance(resolved, ResolvedParams)
        assert isinstance(resolved.params["organism"], MultiPickValue)
        assert bound(resolved.params["organism"]) == ["Plasmodium falciparum 3D7"]
        assert isinstance(resolved.params["strand"], SinglePickValue)
        assert bound(resolved.params["strand"]) == ["sense"]
        assert isinstance(resolved.params["min_tm"], NumberValue)
        assert resolved.params["min_tm"].value == 1.0
        assert isinstance(resolved.params["profileset"], SinglePickValue)
        assert bound(resolved.params["profileset"]) == ["ds_x"]
        assert "samples" not in resolved.params
        assert any(s.param_name == "samples" for s in resolved.open_slots)
        assert "samples" in resolved.unresolved_required

    async def test_a_user_override_fills_an_open_slot(self) -> None:
        stage = fetcher(
            param_info(
                "samples_de_comp",
                allowed=[
                    VocabOption(value="gametocyte", display="Gametocyte"),
                    VocabOption(value="asexual", display="Asexual blood stage"),
                ],
            )
        )

        without = await _walk(fetch_at=stage)
        assert any(s.param_name == "samples_de_comp" for s in without.open_slots)

        filled = await _walk(
            fetch_at=stage,
            stated={"samples_de_comp": "gametocyte"},
        )
        assert filled.open_slots == []
        assert bound(filled.params["samples_de_comp"]) == ["gametocyte"]


def _pct() -> ParameterInfo:
    return param_info(
        "min_expression_percentile",
        "string",
        display_name="Min pct",
        is_number=True,
        default="80",
    )


def _stage() -> ParameterInfo:
    return param_info(
        "stage",
        display_name="Stage",
        leaves=[
            VocabOption(value="gametocyte", display="Gametocyte"),
            VocabOption(value="ring", display="Ring"),
        ],
    )


class TestAnUnknownOverrideIsRefused:
    """An override that names no parameter is an error, not a silent no-op."""

    async def test_a_misspelled_override_raises_with_the_real_names(self) -> None:
        with pytest.raises(UnknownParameterError) as info:
            await _walk(
                fetch_at=fetcher(_pct()),
                intent=ParamIntent(text="top 10 percent"),
                stated={"min_percentile": "90"},
            )

        assert info.value.unknown == ["min_percentile"]
        assert info.value.valid == ["min_expression_percentile"]

    async def test_it_is_a_validation_error_carrying_every_unknown_name(self) -> None:
        with pytest.raises(UnknownParameterError) as info:
            await _walk(
                fetch_at=fetcher(_pct(), _stage()),
                intent=ParamIntent(text="top 10 percent"),
                stated={"percentile": "90", "life_stage": "gametocyte"},
            )

        exc = info.value
        assert isinstance(exc, ValidationError)
        assert exc.code is VEuPathDBErrorCode.VALIDATION_ERROR
        assert exc.unknown == ["life_stage", "percentile"]
        assert exc.valid == ["min_expression_percentile", "stage"]
        assert exc.errors == [{"param": "life_stage"}, {"param": "percentile"}]
        assert exc.detail is not None
        assert "min_expression_percentile" in exc.detail

    async def test_a_known_override_still_resolves(self) -> None:
        resolved = await _walk(
            fetch_at=fetcher(_stage()),
            intent=ParamIntent(text="anything"),
            stated={"stage": "gametocyte"},
        )

        assert bound(resolved.params["stage"]) == ["gametocyte"]

    async def test_no_overrides_never_raises(self) -> None:
        resolved = await _walk(
            fetch_at=fetcher(_pct()),
            intent=ParamIntent(text="anything"),
        )

        assert "min_expression_percentile" in resolved.params

    async def test_an_override_for_a_dependent_param_is_not_refused(self) -> None:
        # A param whose vocabulary depends on a parent is still named on the first
        # fetch, so overriding it must not read as an unknown name.
        async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
            leaves = (
                [VocabOption(value="gametocyte", display="Gametocyte")]
                if "profileset" in context
                else []
            )
            return [
                param_info(
                    "profileset",
                    display_name="Profile set",
                    leaves=[VocabOption(value="ps1", display="Profile Set 1")],
                ),
                param_info(
                    "stage",
                    display_name="Stage",
                    leaves=leaves,
                    depends_on=["profileset"],
                ),
            ]

        resolved = await _walk(
            fetch_at=declaring(fetch_at),
            intent=ParamIntent(text="anything"),
            stated={"stage": "gametocyte"},
        )

        assert bound(resolved.params["stage"]) == ["gametocyte"]


_SEARCH = "GenesByOrthologPattern"


def _wdk_param(
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


def _published() -> WDKSearchResponse:
    return wdk_search_response(
        _SEARCH,
        [
            _wdk_param("organism"),
            _wdk_param(
                "phyletic_indent_map", visible=False, allow_empty=True, default="[]"
            ),
            _wdk_param(
                "phyletic_term_map", visible=False, allow_empty=True, default="[]"
            ),
        ],
        level="NONE",
        is_valid=False,
    )


class _Client:
    """Counts the reads the walk makes directly, bypassing the catalog."""

    def __init__(self) -> None:
        self.static_calls = 0
        self.contexts: list[dict[str, str]] = []

    async def get_search_details(
        self, record_type: str, search_name: str, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del record_type, search_name, expand_params
        self.static_calls += 1
        return _published()

    async def get_search_details_with_params(
        self,
        record_type: str,
        search_name: str,
        context: dict[str, str],
        *,
        expand_params: bool = True,
    ) -> WDKSearchResponse:
        del record_type, search_name, expand_params
        self.contexts.append(dict(context))
        return _published()


class _Discovery:
    """Caches per search, the way ``SearchCatalog.get_search_details`` does."""

    def __init__(self) -> None:
        self.reads = 0
        self._cache: dict[str, WDKSearchResponse] = {}

    async def get_search_details(
        self, ctx: SearchContext, *, expand_params: bool = True
    ) -> WDKSearchResponse:
        del expand_params
        key = f"{ctx.record_type}/{ctx.search_name}"
        if key not in self._cache:
            self.reads += 1
            self._cache[key] = _published()
        return self._cache[key]


@pytest.fixture
def wdk(monkeypatch: pytest.MonkeyPatch) -> tuple[_Client, _Discovery]:
    client = _Client()
    discovery = _Discovery()
    monkeypatch.setattr(param_dag, "get_wdk_client", lambda site_id: client)
    monkeypatch.setattr(param_dag, "get_discovery_service", lambda: discovery)
    return client, discovery


async def _two_passes() -> None:
    fetch = param_dag.wdk_fetch_at("plasmodb", "transcript", _SEARCH)
    await fetch({})
    await fetch({"organism": '["Plasmodium falciparum 3D7"]'})


class TestTheFetcherReadsThePublishedViewOnce:
    """The walk needs the published shape on every pass; reading it through the
    discovery catalog keeps that at one HTTP GET for the whole walk."""

    async def test_the_catalog_answers_one_static_read(
        self, wdk: tuple[_Client, _Discovery]
    ) -> None:
        _, discovery = wdk

        await _two_passes()

        assert discovery.reads == 1

    async def test_the_walk_never_reads_around_the_catalog(
        self, wdk: tuple[_Client, _Discovery]
    ) -> None:
        client, _ = wdk

        await _two_passes()

        assert client.static_calls == 0

    async def test_the_published_shape_completes_the_context(
        self, wdk: tuple[_Client, _Discovery]
    ) -> None:
        client, _ = wdk

        await _two_passes()

        assert client.contexts == [
            {
                "organism": '["Plasmodium falciparum 3D7"]',
                "phyletic_indent_map": "[]",
                "phyletic_term_map": "[]",
            }
        ]
