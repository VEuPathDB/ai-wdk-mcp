"""Validation of search parameter values."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from veupathdb import JSONObject, get_logger
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    PHYLETIC_EXPRESSION_PARAM,
    PHYLETIC_PARAM_NAMES,
    ParameterCanonicalizer,
    ParamGraph,
    ParamSpecNormalized,
    ParamValue,
    PhyleticExpression,
    StringValue,
    VocabularyEntryError,
    canonical_census_pattern,
    check_expression,
    fill_site_set_defaults,
    filled_site_set_defaults,
    shown_stated,
    to_decoded_map,
)
from veupathdb.domain.strategy import StepValidation
from veupathdb.errors import ValidationError, VEuPathDBError
from veupathdb.model import CamelModel
from veupathdb.wdk import (
    WDKParameter,
    WDKSearchResponse,
    encode_wdk_params,
    get_wdk_client,
    phyletic_tree_of,
)

from veupathdb_mcp.catalog.discovery_service import get_discovery_service
from veupathdb_mcp.catalog.eda_backed import (
    EDA_ANALYSIS_SPEC_PARAM,
    check_eda_parameters,
)
from veupathdb_mcp.catalog.param_adapters import (
    adapt_param_from_wdk,
    adapt_param_specs_from_search,
)
from veupathdb_mcp.catalog.phyletic_logic import admit_expression
from veupathdb_mcp.catalog.search_context import context_for_metadata_read
from veupathdb_mcp.catalog.taxonomy import ortho_taxonomy
from veupathdb_mcp.catalog.vocab_resolve import ResolveContext, ordered_refusal
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

NOTHING_HELD: Mapping[str, ParamValue] = MappingProxyType({})


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
    about: ResolveContext | None,
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
        normalized = await _canonical(
            ParameterCanonicalizer(spec_map),
            _filter_context_values(raw_context, allowed),
            response.search_data.parameters or [],
            about,
        )
    except ValidationError as exc:
        return ValidationResponse(
            validation=ValidationResult(is_valid=False, errors=_refusal_errors(exc))
        )

    judged = resolved.values_were_read and response.validation.rejects()
    return ValidationResponse(
        validation=ValidationResult(
            is_valid=not judged,
            normalized_context_values={
                name: shown_stated(value) for name, value in normalized.items()
            },
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


def _canonical_census_pattern(
    response: WDKSearchResponse, stated: dict[str, ParamValue]
) -> dict[str, ParamValue]:
    """A stated ``profile_pattern`` in the form WDK's census matches.

    WDK answers a pattern in prose with a step id and a valid verdict, so the
    fault is reported here. Only a value stated as text is read: the published
    default is not a census pattern, and a held value is WDK's own. Only a search
    that carries the whole phyletic parameter set is judged.
    """
    specs = response.search_data.parameters or []
    if not {spec.name for spec in specs} >= PHYLETIC_PARAM_NAMES:
        return stated
    match stated.get("profile_pattern"):
        case StringValue(value=pattern):
            canonical = canonical_census_pattern(pattern, phyletic_tree_of(specs))
            return {**stated, "profile_pattern": StringValue(value=canonical)}
        case _:
            return stated


async def _checked_phyletic_expression(
    site_id: str, response: WDKSearchResponse, stated: dict[str, ParamValue]
) -> dict[str, ParamValue]:
    """Judge a stated ``phyletic_expression`` against its grammar and the site's
    taxonomy, and send it as rendered. The site has no spelling of its own, it echoes
    what it receives. OrthoMCL answers a fault with a 500."""
    specs = response.search_data.parameters or []
    if PHYLETIC_EXPRESSION_PARAM not in {spec.name for spec in specs}:
        return stated
    text = encode_wdk_params(stated).get(PHYLETIC_EXPRESSION_PARAM)
    if text is None:
        return stated
    expression = PhyleticExpression.parse(text)
    rendered = expression.render()
    admit_expression(rendered)
    tree = await ortho_taxonomy(site_id)
    if tree is not None:
        check_expression(expression, tree)
    return {**stated, PHYLETIC_EXPRESSION_PARAM: StringValue(value=rendered)}


def _refuses_a_statement(
    validation: StepValidation,
    *,
    stated: Mapping[str, ParamValue],
    context: Mapping[str, ParamValue],
    held_validation: StepValidation | None,
) -> bool:
    """WDK's negative verdict names something a statement introduced.

    Nothing stated introduces nothing. A verdict on a context value, or a
    general error the step's own stored verdict already carried, is WDK's
    judgement of what the step held before, so it never refuses.
    """
    if not stated or not validation.rejects():
        return False
    errors = validation.errors
    if errors is None:
        return True
    if any(key not in context for key in errors.by_key):
        return True
    known = (
        set(held_validation.errors.general)
        if held_validation is not None and held_validation.errors is not None
        else set()
    )
    return any(text not in known for text in errors.general)


async def _canonical(
    canonicalizer: ParameterCanonicalizer,
    values: dict[str, ParamValue],
    declarations: Sequence[WDKParameter],
    about: ResolveContext | None,
) -> dict[str, ParamValue]:
    """The canonical values, or a vocabulary refusal with its candidates ordered
    under ``about``. None leaves the ranking."""
    try:
        return canonicalizer.canonicalize(values)
    except VocabularyEntryError as refusal:
        if about is None:
            raise
        raise await ordered_refusal(refusal, declarations, about) from refusal


async def validate_parameters(
    ctx: SearchContext,
    *,
    stated: Mapping[str, ParamValue],
    context: Mapping[str, ParamValue] = NOTHING_HELD,
    held_validation: StepValidation | None = None,
    callbacks: ValidationCallbacks,
    about: ResolveContext | None,
) -> ValidatedParams:
    """The stated values in the catalog's form, judged under the values the step
    already holds. Only a stated value is canonicalized or refused; a context
    value goes to WDK as it is, and ``held_validation`` is the verdict WDK
    stored for the step. The result holds the stated values and each site-set
    value neither map holds."""
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
    held = {name: value for name, value in context.items() if name not in stated}

    resolved = await resolve_search_details(
        ctx,
        resolved_record_type=resolved_record_type,
        parameters={**held, **stated},
    )
    response = resolved.response
    if stated and EDA_ANALYSIS_SPEC_PARAM not in held:
        check_eda_parameters(
            response.search_data, encode_wdk_params({**held, **stated})
        )

    param_spec_map = adapt_param_specs_from_search(response.search_data)
    written = await _checked_phyletic_expression(ctx.site_id, response, dict(stated))
    written = _canonical_census_pattern(response, written)
    canonical = await _canonical(
        ParameterCanonicalizer(param_spec_map),
        written,
        response.search_data.parameters or [],
        about,
    )

    # A tree param counts only its leaves, so a branch selection scores zero
    # until it is expanded. WDK must judge what will be sent, not what arrived.
    if canonical != written:
        resolved = await resolve_search_details(
            ctx,
            resolved_record_type=resolved_record_type,
            parameters={**held, **canonical},
        )
        response = resolved.response
        param_spec_map = adapt_param_specs_from_search(response.search_data)

    # A definition built without the caller's values judged a different shape,
    # so it casts no verdict either way.
    if resolved.values_were_read and _refuses_a_statement(
        response.validation,
        stated=written,
        context=held,
        held_validation=held_validation,
    ):
        raise wdk_rejection_error(response.validation)

    refreshed_ctx = SearchContext(
        site_id=ctx.site_id,
        record_type=resolved_record_type,
        search_name=ctx.search_name,
    )
    # The refresh below skips a parent whose value is empty, so site-set required
    # parents must get their defaults first.
    param_spec_map = await _refresh_dependent_vocabularies(
        ctx=refreshed_ctx,
        param_spec_map=param_spec_map,
        canonical_values=fill_site_set_defaults(param_spec_map, {**held, **canonical}),
    )
    caller_canonical = await _canonical(
        ParameterCanonicalizer(param_spec_map),
        written,
        response.search_data.parameters or [],
        about,
    )
    filled = fill_site_set_defaults(param_spec_map, {**held, **caller_canonical})
    echoed = {
        spec.name: spec.initial_display_value
        for spec in response.search_data.parameters or []
        if spec.initial_display_value is not None
    }
    # A site-set parameter the host filled is a value nobody chose, so it is
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
        | set(filled_site_set_defaults(param_spec_map, {**held, **caller_canonical}))
    )
    return ValidatedParams(
        params={name: value for name, value in filled.items() if name not in held},
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
    fill_order = ParamGraph.of(list(next_specs.values())).fill_order
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
