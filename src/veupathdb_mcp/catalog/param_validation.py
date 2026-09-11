"""Validation of search parameter values."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from veupathdb import JSONObject, get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    PHYLETIC_PARAM_NAMES,
    ParameterCanonicalizer,
    ParamSpecNormalized,
    ParamValue,
    census_states,
    fill_hidden_required_defaults,
    filled_hidden_defaults,
    to_decoded_map,
    topological_fill_order,
    validate_phyletic_codes,
)
from veupathdb.domain.strategy import StepValidation
from veupathdb.errors import ValidationError, VEuPathDBError
from veupathdb.model import CamelModel
from veupathdb.wdk import (
    WDKSearchResponse,
    encode_wdk_params,
    get_wdk_client,
    phyletic_tree_of,
)

from veupathdb_mcp.catalog.discovery_service import get_discovery_service
from veupathdb_mcp.catalog.eda_backed import check_eda_parameters
from veupathdb_mcp.catalog.param_adapters import (
    adapt_param_from_wdk,
    adapt_param_specs_from_search,
)
from veupathdb_mcp.catalog.search_context import context_for_metadata_read
from veupathdb_mcp.catalog.wdk_substitution import substituted_params
from veupathdb_mcp.tool_errors import ToolErrorPayload

from ._param_validation_errors import (
    collect_available_search_names,
    find_search_record_type_hint,
    unknown_search_error,
    unreadable_search_error,
    wdk_rejection_error,
)
from .param_resolution import (
    _extract_param_names_from_response,
    _filter_context_values,
    get_refreshed_dependent_params,
)

logger = get_logger(__name__)


class _ValidationErrorEntry(BaseModel):
    """One row of an ``VEuPathDBError.errors`` list, in any shape a refusal writes.

    A row that is not an object carries the whole message, so it is read as one.
    """

    model_config = ConfigDict(extra="ignore")
    param: str | None = None
    path: str | None = None
    message: str | None = None
    messages: list[str] = Field(default_factory=list)
    detail: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _a_row_that_is_not_an_object_is_one_message(cls, value: object) -> object:
        return value if isinstance(value, Mapping) else {"message": str(value)}


_REFUSAL_ROWS: TypeAdapter[list[_ValidationErrorEntry]] = TypeAdapter(
    list[_ValidationErrorEntry]
)


class ValidationErrors(CamelModel):
    """Structured validation errors by category."""

    general: list[str] = Field(default_factory=list)
    by_key: dict[str, list[str]] = Field(default_factory=dict)


class ValidationResult(CamelModel):
    """Single validation result with normalized values."""

    is_valid: bool
    normalized_context_values: JSONObject = Field(default_factory=dict)
    errors: ValidationErrors = Field(default_factory=ValidationErrors)


class ValidationResponse(CamelModel):
    """Top-level validation response wrapper."""

    validation: ValidationResult


@dataclass(frozen=True)
class ValidationCallbacks:
    """Caller-provided callbacks for parameter validation.

    Set the payload callback only when the caller must turn a validation error
    into a tool error payload.
    """

    resolve_record_type_for_search: Callable[
        [str | None, str | None], Awaitable[str | None]
    ]
    find_record_type_hint: Callable[[str, str | None], Awaitable[str | None]]
    validation_error_payload: Callable[[ValidationError], ToolErrorPayload] | None = (
        None
    )


@dataclass(frozen=True)
class ResolvedSearch:
    """A search definition, and whether WDK built it from the caller's values."""

    response: WDKSearchResponse
    values_were_read: bool


async def resolve_search_details(
    ctx: SearchContext,
    *,
    resolved_record_type: str,
    parameters: dict[str, ParamValue],
) -> ResolvedSearch:
    """The search definition WDK builds from the caller's values.

    The catalog's published specs answer instead when the contextual read
    fails, and the result says which of the two it carries. A reader that
    returns a bare definition drops that flag, this fallback, and the error a
    search WDK cannot read raises.
    """
    discovery = get_discovery_service()
    try:
        wdk_client = get_wdk_client(ctx.site_id)
        resolved_ctx = SearchContext(ctx.site_id, resolved_record_type, ctx.search_name)
        published = await discovery.get_search_details(resolved_ctx, expand_params=True)
        context = context_for_metadata_read(
            encode_wdk_params(parameters), published.search_data.parameters
        )
        try:
            return ResolvedSearch(
                response=await wdk_client.get_search_details_with_params(
                    resolved_record_type,
                    ctx.search_name,
                    context=context,
                    expand_params=True,
                ),
                values_were_read=True,
            )
        except VEuPathDBError as exc:
            logger.warning(
                "Contextual param fetch failed, falling back to non-contextual specs",
                record_type=resolved_record_type,
                search_name=ctx.search_name,
                error=str(exc),
            )
            return ResolvedSearch(response=published, values_were_read=False)
    except VEuPathDBError as exc:
        hint_record_type = await find_search_record_type_hint(discovery, ctx)
        available = await collect_available_search_names(
            discovery, ctx.site_id, resolved_record_type
        )
        raise unreadable_search_error(
            search_name=ctx.search_name,
            record_type=resolved_record_type,
            detail=str(exc),
            available_searches=available,
            record_type_hint=hint_record_type,
        ) from exc


def _bundle_errors(validation: StepValidation) -> ValidationErrors:
    """WDK's own per-parameter verdict, in the shape the frontend reads."""
    if validation.errors is None:
        return ValidationErrors()
    return ValidationErrors(
        general=list(validation.errors.general),
        by_key={key: list(texts) for key, texts in validation.errors.by_key.items()},
    )


def _refusal_errors(exc: ValidationError) -> ValidationErrors:
    """A canonicalizer refusal, keyed by the parameter it names."""
    fallback = exc.detail or exc.title
    by_key: dict[str, list[str]] = {}
    general: list[str] = []
    for entry in _REFUSAL_ROWS.validate_python(exc.errors or []):
        texts = entry.messages or [entry.message or entry.detail or fallback]
        param_name = entry.param or entry.path
        if param_name:
            by_key.setdefault(param_name, []).extend(texts)
        else:
            general.extend(texts)
    return ValidationErrors(general=general or [fallback], by_key=by_key)


async def validate_search_params(
    ctx: SearchContext,
    *,
    context_values: dict[str, ParamValue] | None,
) -> ValidationResponse:
    """Validate and canonicalize search parameters for the UI.

    The frontend consumes this result. It never interprets raw WDK payloads.
    A definition WDK built without these values judged a different shape, so it
    casts no verdict and the save proceeds to the push that does.
    """
    raw_context: dict[str, ParamValue] = context_values or {}
    try:
        resolved = await resolve_search_details(
            ctx, resolved_record_type=ctx.record_type, parameters=raw_context
        )
    except VEuPathDBError as exc:
        return ValidationResponse(
            validation=ValidationResult(
                is_valid=False,
                errors=ValidationErrors(
                    general=[f"Failed to load search metadata: {exc}"]
                ),
            )
        )

    response = resolved.response
    allowed = _extract_param_names_from_response(response)
    spec_map = adapt_param_specs_from_search(response.search_data)
    try:
        canonicalizer = ParameterCanonicalizer(spec_map)
        normalized = canonicalizer.canonicalize(
            _filter_context_values(raw_context, allowed)
        )
    except ValidationError as exc:
        return ValidationResponse(
            validation=ValidationResult(is_valid=False, errors=_refusal_errors(exc))
        )

    judged = resolved.values_were_read and response.validation.rejects()
    return ValidationResponse(
        validation=ValidationResult(
            is_valid=not judged,
            normalized_context_values=to_decoded_map(normalized),
            errors=_bundle_errors(response.validation)
            if judged
            else ValidationErrors(),
        )
    )


class ValidatedParams(CamelModel):
    """Canonical values, the record class WDK lists the search under, and the
    names WDK supplied rather than accepted."""

    params: dict[str, ParamValue] = Field(default_factory=dict)
    record_class: str | None = None
    substituted: list[str] = Field(default_factory=list)


def _refuse_bad_census_pattern(
    response: WDKSearchResponse, canonical: dict[str, ParamValue]
) -> None:
    """Judge a stated ``profile_pattern`` against the census grammar.

    WDK answers a pattern in prose with a step id and a valid verdict, so this
    is the only place the fault can be reported. The published default is not a
    census pattern, so only a value the caller stated is judged, and only on a
    search that carries the whole phyletic parameter set.
    """
    specs = response.search_data.parameters or []
    if not {spec.name for spec in specs} >= PHYLETIC_PARAM_NAMES:
        return
    pattern = encode_wdk_params(canonical).get("profile_pattern")
    if pattern is None:
        return
    states = census_states(pattern)
    tree = phyletic_tree_of(specs)
    if states and tree is not None:
        validate_phyletic_codes(list(states), {node.code for node in tree.nodes()})


async def validate_parameters(
    ctx: SearchContext,
    *,
    parameters: dict[str, ParamValue],
    callbacks: ValidationCallbacks,
) -> ValidatedParams:
    resolved_record_type = await callbacks.resolve_record_type_for_search(
        ctx.record_type, ctx.search_name
    )
    if resolved_record_type is None:
        record_type_hint = await callbacks.find_record_type_hint(
            ctx.search_name, ctx.record_type
        )
        raise unknown_search_error(
            search_name=ctx.search_name,
            record_type=ctx.record_type,
            record_type_hint=record_type_hint,
        )

    resolved = await resolve_search_details(
        ctx,
        resolved_record_type=resolved_record_type,
        parameters=parameters,
    )
    response = resolved.response
    check_eda_parameters(response.search_data, encode_wdk_params(parameters))

    param_spec_map = adapt_param_specs_from_search(response.search_data)
    canonicalizer = ParameterCanonicalizer(param_spec_map)
    canonical: dict[str, ParamValue] = canonicalizer.canonicalize(parameters)
    _refuse_bad_census_pattern(response, canonical)

    # A tree param counts only its leaves, so a branch selection scores zero
    # until it is expanded. WDK must judge what will be sent, not what arrived.
    if encode_wdk_params(canonical) != encode_wdk_params(parameters):
        resolved = await resolve_search_details(
            ctx,
            resolved_record_type=resolved_record_type,
            parameters=canonical,
        )
        response = resolved.response
        param_spec_map = adapt_param_specs_from_search(response.search_data)

    # WDK validated these values while answering, and its verdict is the
    # refusal. A definition built without the caller's values judged a
    # different shape, so it casts no verdict either way.
    if resolved.values_were_read and response.validation.rejects():
        raise wdk_rejection_error(response.validation)

    refreshed_ctx = SearchContext(
        site_id=ctx.site_id,
        record_type=resolved_record_type,
        search_name=ctx.search_name,
    )
    # The refresh below skips a parent whose value is empty, so hidden required
    # parents must get their defaults first.
    canonical = fill_hidden_required_defaults(param_spec_map, canonical)
    param_spec_map = await _refresh_dependent_vocabularies(
        ctx=refreshed_ctx,
        param_spec_map=param_spec_map,
        canonical_values=canonical,
    )
    canonicalizer = ParameterCanonicalizer(param_spec_map)
    caller_canonical = canonicalizer.canonicalize(parameters)
    canonical = fill_hidden_required_defaults(param_spec_map, caller_canonical)
    echoed = {
        spec.name: spec.initial_display_value
        for spec in response.search_data.parameters or []
        if spec.initial_display_value is not None
    }
    # A hidden parameter the host filled is a value nobody chose, so it is
    # reported alongside the ones WDK substituted. Both are read against the
    # caller's own canonical values, which is what WDK was asked to judge.
    substituted = sorted(
        set(
            substituted_params(
                sent=caller_canonical,
                echoed=echoed,
                specs=param_spec_map,
                values_were_read=resolved.values_were_read,
            )
        )
        | set(filled_hidden_defaults(param_spec_map, caller_canonical))
    )
    return ValidatedParams(
        params=canonical,
        record_class=resolved_record_type,
        substituted=substituted,
    )


async def _refresh_dependent_vocabularies(
    *,
    ctx: SearchContext,
    param_spec_map: dict[str, ParamSpecNormalized],
    canonical_values: dict[str, ParamValue],
) -> dict[str, ParamSpecNormalized]:
    """Refresh each dependent vocabulary against its parent's canonical value.

    A parent with an empty value keeps the static child vocabulary. A failed
    refresh also keeps the static vocabulary.
    """
    next_specs = dict(param_spec_map)
    fill_order = topological_fill_order(next_specs)
    decoded_values = to_decoded_map(canonical_values)
    for parent_name in fill_order:
        parent = next_specs.get(parent_name)
        if parent is None or not parent.dependent_params:
            continue
        parent_value = decoded_values.get(parent_name)
        if parent_value in (None, "", [], {}):
            continue
        try:
            refreshed = await get_refreshed_dependent_params(
                ctx,
                parameter_name=parent_name,
                context_values=canonical_values,
            )
        except VEuPathDBError as exc:
            logger.warning(
                "refreshed-dependent-params failed; falling back to static vocab",
                parent=parent_name,
                search=ctx.search_name,
                error=str(exc),
            )
            continue
        for refreshed_param in refreshed:
            if refreshed_param.name in parent.dependent_params:
                next_specs[refreshed_param.name] = adapt_param_from_wdk(refreshed_param)
    return next_specs
