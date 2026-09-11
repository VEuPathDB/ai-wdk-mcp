"""The parameter DAG walk: filter params, dependent chains, unknown names, and
the fetcher that reads WDK."""

from __future__ import annotations

import pytest
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    FilterValue,
    MultiPickValue,
    NumberValue,
    SinglePickValue,
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
from veupathdb_mcp.catalog.param_formatting import FilterFieldInfo
from veupathdb_mcp.catalog.param_intent import ParamIntent

from .conftest import bound, fetcher, param_info, vocab, wdk_search_response

Clauses = list[tuple[str, str, bool, list[str]]]

_SAMPLE_FACETS = [
    FilterFieldInfo(
        term="Sample type",
        display="Sample type",
        type="string",
        values=["specimen from organism", "culture", "blood"],
    ),
    FilterFieldInfo(term="Country", display="Country", type="string", values=["India"]),
]
_FULL_FILTER_JSON = (
    '{"filters": [{"field": "Sample type", "type": "string", "isRange": false, '
    '"includeUnknown": false, "value": ["culture", "blood"]}]}'
)
_PARTIAL_FILTER_JSON = (
    '{"filters": [{"field": "Sample type", "value": "specimen from organism"}]}'
)


def _filter(name: str, fields: list[FilterFieldInfo]) -> ParameterInfo:
    return param_info(name, "filter", filter_fields=fields)


def _strain_meta() -> ParamFetcher:
    return fetcher(_filter("ngsSnp_strain_meta", _SAMPLE_FACETS))


class TestFilterParams:
    async def test_a_filter_param_defaults_to_include_all(self) -> None:
        """The WDK default for a filter param is the empty filter set, and it
        resolves rather than opening a slot."""
        resolved = await resolve_params_with_intent(
            fetch_at=_strain_meta(), intent=ParamIntent()
        )

        value = resolved.params["ngsSnp_strain_meta"]
        assert isinstance(value, FilterValue)
        assert value.filters == []
        assert value.to_wire() == '{"filters": []}'
        assert resolved.unresolved_required == []
        assert resolved.open_slots == []

    @pytest.mark.parametrize(
        ("override", "expected"),
        [
            (
                "Sample type=culture,blood",
                [("Sample type", "string", False, ["culture", "blood"])],
            ),
            ("sample type=culture", [("Sample type", "string", False, ["culture"])]),
            (
                _FULL_FILTER_JSON,
                [("Sample type", "string", False, ["culture", "blood"])],
            ),
            (
                _PARTIAL_FILTER_JSON,
                [("Sample type", "string", False, ["specimen from organism"])],
            ),
            ('{"filters": []}', []),
            ("not a filter at all", []),
        ],
    )
    async def test_an_override_builds_the_clauses_the_ontology_types(
        self, override: str, expected: Clauses
    ) -> None:
        resolved = await resolve_params_with_intent(
            fetch_at=_strain_meta(),
            intent=ParamIntent(),
            overrides={"ngsSnp_strain_meta": override},
        )

        value = resolved.params["ngsSnp_strain_meta"]
        assert isinstance(value, FilterValue)
        assert [
            (c.field, c.type, c.is_range, c.value) for c in value.filters
        ] == expected

    async def test_an_override_without_a_facet_means_include_all(self) -> None:
        resolved = await resolve_params_with_intent(
            fetch_at=_strain_meta(),
            intent=ParamIntent(),
            overrides={"ngsSnp_strain_meta": "All field isolates"},
        )

        value = resolved.params["ngsSnp_strain_meta"]
        assert isinstance(value, FilterValue)
        assert value.filters == []
        assert not any(
            s.param_name == "ngsSnp_strain_meta" for s in resolved.open_slots
        )


_LOFFLER_FACETS = [
    FilterFieldInfo(
        term="PCR result",
        display="PCR result",
        type="string",
        values=["Negative", "Positive"],
    )
]


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
        resolved = await resolve_params_with_intent(
            fetch_at=_loffler(), intent=ParamIntent()
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
        resolved = await resolve_params_with_intent(
            fetch_at=_loffler(),
            intent=ParamIntent(),
            overrides={
                "ref_samples_filter_metadata_loffler": "PCR result=Negative",
                "comp_samples_filter_metadata_loffler": "PCR result=Positive",
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

        resolved = await resolve_params_with_intent(
            fetch_at=fetch_at,
            intent=ParamIntent(),
            overrides={"organism": "Plasmodium falciparum 3D7"},
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

        without = await resolve_params_with_intent(fetch_at=stage, intent=ParamIntent())
        assert any(s.param_name == "samples_de_comp" for s in without.open_slots)

        filled = await resolve_params_with_intent(
            fetch_at=stage,
            intent=ParamIntent(),
            overrides={"samples_de_comp": "Gametocyte"},
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
            await resolve_params_with_intent(
                fetch_at=fetcher(_pct()),
                intent=ParamIntent(text="top 10 percent"),
                overrides={"min_percentile": "90"},
            )

        assert info.value.unknown == ["min_percentile"]
        assert info.value.valid == ["min_expression_percentile"]

    async def test_it_is_a_validation_error_carrying_every_unknown_name(self) -> None:
        with pytest.raises(UnknownParameterError) as info:
            await resolve_params_with_intent(
                fetch_at=fetcher(_pct(), _stage()),
                intent=ParamIntent(text="top 10 percent"),
                overrides={"percentile": "90", "life_stage": "gametocyte"},
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
        resolved = await resolve_params_with_intent(
            fetch_at=fetcher(_stage()),
            intent=ParamIntent(text="anything"),
            overrides={"stage": "Gametocyte"},
        )

        assert bound(resolved.params["stage"]) == ["gametocyte"]

    async def test_no_overrides_never_raises(self) -> None:
        resolved = await resolve_params_with_intent(
            fetch_at=fetcher(_pct()), intent=ParamIntent(text="anything")
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

        resolved = await resolve_params_with_intent(
            fetch_at=fetch_at,
            intent=ParamIntent(text="anything"),
            overrides={"stage": "gametocyte"},
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
