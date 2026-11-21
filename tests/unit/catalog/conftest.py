"""Builders shared by the catalog service tests."""

from __future__ import annotations

from typing import Final, Literal, TypedDict, Unpack, cast

from pydantic import JsonValue, TypeAdapter
from veupathdb import JSONObject
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    FilterFacet,
    MultiPickValue,
    ParamValue,
    SinglePickValue,
    VocabOption,
    WDKVocabTerm,
)
from veupathdb.domain.strategy import StepValidation
from veupathdb.wdk import (
    WDKEnumParam,
    WDKParameter,
    WDKSearch,
    WDKSearchResponse,
    WDKStringParam,
)

from veupathdb_mcp.catalog.param_dag import ParamFetcher
from veupathdb_mcp.catalog.param_formatting import ParameterInfo
from veupathdb_mcp.catalog.param_validation import ValidationCallbacks

PHYLETIC_STRAIN = "Plasmodium falciparum 3D7"
PHYLETIC_MAPS = ("phyletic_indent_map", "phyletic_term_map")


class ParamFields(TypedDict, total=False):
    """The optional fields a test parameter sets, under short names."""

    display_name: str
    allowed: list[VocabOption] | None
    leaves: list[VocabOption]
    default: str | None
    required: bool
    visible: bool
    site_set: bool
    is_number: bool
    depends_on: list[str]
    filter_fields: list[FilterFacet]
    tree: str | None
    help_text: str


_INFO_FIELD_NAMES: Final[dict[str, str]] = {
    "display_name": "display_name",
    "allowed": "allowed_values",
    "leaves": "vocab_leaves",
    "default": "default_value",
    "required": "required",
    "visible": "is_visible",
    "site_set": "site_set",
    "is_number": "is_number",
    "depends_on": "wire_parents",
    "filter_fields": "filter_fields",
    "tree": "allowed_values_tree",
    "help_text": "help",
}


def param_info(
    name: str,
    param_type: str = "single-pick-vocabulary",
    **fields: Unpack[ParamFields],
) -> ParameterInfo:
    """A formatted parameter, with every field the walk reads."""
    payload: dict[str, object] = {
        "name": name,
        "display_name": name,
        "type": param_type,
        "required": True,
        "is_visible": True,
        "site_set": False,
        "is_number": False,
        "help": "",
    }
    payload.update((_INFO_FIELD_NAMES[key], value) for key, value in fields.items())
    return ParameterInfo.model_validate(payload)


def facet(
    term: str,
    facet_type: Literal["string", "number", "date"] = "string",
    *,
    display: str | None = None,
    is_range: bool = False,
    members: tuple[str, ...] = (),
) -> FilterFacet:
    return FilterFacet(
        term=term,
        display=display or term,
        parent=None,
        type=facet_type,
        is_range=is_range,
        units=None,
        precision=0,
        members=list(members),
    )


def vocab(*values: str) -> list[VocabOption]:
    """Options whose display equals their term."""
    return [VocabOption(value=value, display=value) for value in values]


def vocab_terms(*pairs: tuple[str, str]) -> list[WDKVocabTerm]:
    return [WDKVocabTerm((term, display, None)) for term, display in pairs]


def fetcher(*infos: ParameterInfo) -> ParamFetcher:
    """A fetcher that answers the same parameters at every context."""

    async def fetch_at(context: dict[str, str]) -> list[ParameterInfo]:
        del context
        return list(infos)

    return fetch_at


_DECLARATION: TypeAdapter[WDKParameter] = TypeAdapter(WDKParameter)


def declared(*infos: ParameterInfo) -> list[WDKParameter]:
    """The published declaration each test parameter stands for."""
    return [
        _DECLARATION.validate_python(
            {
                "name": info.name,
                "displayName": info.display_name,
                "type": info.param_kind,
                "isNumber": info.is_number,
                "isVisible": info.is_visible,
                "min": info.min,
                "max": info.max,
                "vocabulary": [[o.value, o.display, None] for o in info.vocabulary()]
                or None,
                "ontology": [
                    {
                        "term": f.term,
                        "display": f.display,
                        "type": f.type,
                        "isRange": f.is_range,
                    }
                    for f in info.facets().root
                ],
                "values": {f.term: f.members for f in info.facets().root},
            }
        )
        for info in infos
    ]


def bound(value: ParamValue) -> list[str]:
    """Either vocabulary kind as a list of bare terms."""
    if isinstance(value, MultiPickValue):
        return list(value.values)
    if isinstance(value, SinglePickValue):
        return [value.value]
    msg = f"unexpected param value: {value!r}"
    raise AssertionError(msg)


def hidden_map_param(name: str) -> WDKParameter:
    """A hidden checkbox param that carries the empty selection."""
    raw: JSONObject = {
        "type": "multi-pick-vocabulary",
        "name": name,
        "display_name": name,
        "display_type": "checkBox",
        "is_visible": False,
        "allow_empty_value": True,
        "initial_display_value": "[]",
    }
    return cast("WDKParameter", WDKEnumParam.model_validate(raw))


def organism_param(initial: str) -> WDKParameter:
    """The tree-box organism param of the phyletic search."""
    raw: JSONObject = {
        "type": "multi-pick-vocabulary",
        "name": "organism",
        "display_name": "Organism",
        "display_type": "treeBox",
        "allow_empty_value": False,
        "initial_display_value": initial,
        "vocabulary": cast("JsonValue", [[PHYLETIC_STRAIN, PHYLETIC_STRAIN, None]]),
    }
    return cast("WDKParameter", WDKEnumParam.model_validate(raw))


def phyletic_search_params(
    *, pattern: str = "hsap=1T", organism_initial: str = "[]"
) -> list[WDKParameter]:
    """``GenesByOrthologPattern`` as WDK publishes it."""
    profile_pattern = WDKStringParam(
        name="profile_pattern",
        display_name="profile_pattern",
        is_visible=False,
        allow_empty_value=False,
        initial_display_value=pattern,
    )
    species_lists = [
        WDKStringParam(
            name=name,
            display_name=name,
            allow_empty_value=True,
            initial_display_value=initial,
        )
        for name, initial in (
            ("included_species", "pfal"),
            ("excluded_species", "hsap"),
        )
    ]
    return [
        profile_pattern,
        *species_lists,
        *(hidden_map_param(name) for name in PHYLETIC_MAPS),
        organism_param(organism_initial),
    ]


def wdk_search_response(
    search_name: str,
    parameters: list[WDKParameter],
    *,
    level: str = "SEMANTIC",
    is_valid: bool = True,
    errors: JSONObject | None = None,
    query_name: str = "",
) -> WDKSearchResponse:
    return WDKSearchResponse(
        search_data=WDKSearch(
            url_segment=search_name,
            full_name=search_name,
            display_name=search_name,
            query_name=query_name,
            param_names=[p.name for p in parameters],
            parameters=parameters,
        ),
        validation=StepValidation.model_validate(
            {"level": level, "isValid": is_valid, "errors": errors}
        ),
    )


def validation_callbacks() -> ValidationCallbacks:
    """Callbacks that echo the record type and offer no hint."""

    async def _resolve(record_type: str | None, search_name: str | None) -> str | None:
        del search_name
        return record_type

    async def _hint(search_name: str, record_type: str | None) -> str | None:
        del search_name, record_type
        return None

    return ValidationCallbacks(
        resolve_record_type_for_search=_resolve, find_record_type_hint=_hint
    )


async def no_dependent_refresh(
    ctx: SearchContext, *, parameter_name: str, context_values: JSONObject
) -> list[WDKParameter]:
    del ctx, parameter_name, context_values
    return []
