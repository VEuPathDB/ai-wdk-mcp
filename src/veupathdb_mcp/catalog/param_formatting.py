"""Pure formatting of WDK parameter specs into AI-facing info objects."""

from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, ValidationError, model_validator
from veupathdb.domain.parameters.phyletic import PHYLETIC_MAP_PARAMS
from veupathdb.domain.parameters.specs import ParamSpecNormalized
from veupathdb.domain.parameters.values import ParamKind, ParamValue
from veupathdb.domain.parameters.wdk_vocab import (
    VocabOption,
    WDKTreeBoxVocabNode,
    WDKVocabulary,
    dedupe_options,
    flatten_vocab,
)
from veupathdb.model import CamelModel
from veupathdb.wdk.phyletic_tree import phyletic_tree_of
from veupathdb.wdk.wdk_parameters import WDKParameter

from veupathdb_mcp.catalog.eda_backed import (
    UPLOAD_SENTINEL_NOTE,
    is_upload_sentinel_vocabulary,
)
from veupathdb_mcp.catalog.vocab_rendering import (
    _MAX_VOCAB_ENTRIES,
    allowed_values,
    render_vocab_tree,
)

PHYLETIC_LIST_PARAMS = frozenset({"included_species", "excluded_species"})
"""The two visible parameters that state a phyletic criterion."""

_PHYLETIC_LIST_HELP = (
    "Species or clade codes from the phyletic tree, comma-separated or a list; "
    "a clade selects all of its species; profile_pattern is derived from these "
    "two lists."
)


_VALUE_FORMAT_TEMPLATES: dict[str, str] = {
    "string": '{"type": "string", "value": "<your value>"}',
    "number": '{"type": "number", "value": <number>}',
    "number-range": '{"type": "number-range", "min": <number>, "max": <number>}',
    "date": '{"type": "date", "value": "<YYYY-MM-DD>"}',
    "date-range": '{"type": "date-range", "min": "<YYYY-MM-DD>", "max": "<YYYY-MM-DD>"}',
    "timestamp": '{"type": "timestamp", "value": "<ISO-8601>"}',
    "single-pick-vocabulary": '{"type": "single-pick-vocabulary", "value": "<one of allowed_values>"}',
    "multi-pick-vocabulary": '{"type": "multi-pick-vocabulary", "values": ["<from allowed_values>", "..."]}',
    "filter": '{"type": "filter", "filters": [{"field": "<field>", "value": <value>}]}',
    "input-dataset": '{"type": "input-dataset", "datasetId": "<id>"}',
    "input-step": '{"type": "input-step", "stepId": "<id>"}',
}


def _value_format(param_type: str) -> str:
    return _VALUE_FORMAT_TEMPLATES.get(
        param_type,
        '{"type": "string", "value": "<your value>"}',
    )


_PARAM_KIND_ADAPTER: TypeAdapter[ParamKind] = TypeAdapter(ParamKind)


def _to_param_kind(type_str: str) -> ParamKind:
    try:
        return _PARAM_KIND_ADAPTER.validate_python(type_str)
    except ValidationError:
        return "string"


_PROFILE_PATTERN_HELP = (
    "Phylogenetic profile pattern. It is DERIVED from included_species and "
    "excluded_species; never write it. State the criterion by naming species or "
    "clades in those two lists.\n"
    "\n"
    "CRITICAL: The 'organism' parameter controls which organisms' genes appear in "
    "results. Select every relevant organism by listing the leaf values from the "
    "organism vocabulary tree. A parent term selects the leaves beneath it. "
    "If you only select one organism, you will get 0 results even if the pattern is correct."
)


class FilterFieldInfo(CamelModel):
    """A selectable facet of a WDK filter param: one leaf ontology term with its values."""

    term: str
    display: str
    type: str
    is_range: bool = False
    values: list[str] = Field(default_factory=list)


class ParameterInfo(CamelModel):
    """Formatted WDK parameter info for AI tool consumption."""

    kind: Literal["parameter_info"] = "parameter_info"
    name: str
    display_name: str
    type: str
    required: bool
    is_visible: bool
    # WDK reports numeric bounds as ``type: "string"`` with ``isNumber: true``.
    is_number: bool = False
    help: str
    value_format: str
    default_value: str | None = None
    min: float | None = None
    max: float | None = None
    allowed_values: list[VocabOption] | None = None
    allowed_values_tree: str | None = None
    allowed_values_note: str | None = None
    controls_vocab_of: list[str] | None = None
    vocab_depends_on: list[str] | None = None
    note: str | None = None
    filter_fields: list[FilterFieldInfo] = Field(default_factory=list)
    # Flattened vocabulary leaves for internal matching. Never sent to the model.
    vocab_leaves: list[VocabOption] = Field(default_factory=list, exclude=True)
    # `type` is the WDK ParamKind; `kind` is the model discriminator.
    param_kind: ParamKind = "string"

    @model_validator(mode="after")
    def _derive_param_kind(self) -> Self:
        self.param_kind = _to_param_kind(self.type)
        return self

    def vocabulary(self) -> list[VocabOption]:
        """The whole option list when it was flattened, else the capped view."""
        return dedupe_options(self.vocab_leaves or self.allowed_values or [])


class ParameterNotOnSearch(CamelModel):
    """Returned when ``parameter_id`` is not a parameter of ``search_name``.

    This is a normal tool return, so it does not consume retry budget.
    """

    kind: Literal["parameter_not_on_search"] = "parameter_not_on_search"
    search_name: str
    requested_parameter_id: str
    message: str
    suggestions: list[str]
    valid_parameter_ids: list[str]


class ParentContextRequired(CamelModel):
    """Returned when a dependent parameter is read with no parent value bound.

    The vocabulary is generated under the parents, so without them there is no
    single answer to give. This is a normal tool return.
    """

    kind: Literal["parent_context_required"] = "parent_context_required"
    search_name: str
    parameter_id: str
    parent_parameter_ids: list[str]
    message: str


GetParameterOptionsResult = Annotated[
    ParameterInfo | ParameterNotOnSearch | ParentContextRequired,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Typed API (accepts list[WDKParameter])
# ---------------------------------------------------------------------------


def _build_typed_dependency_map(
    params: list[WDKParameter],
) -> dict[str, list[str]]:
    """Map each child param to the parent params that determine its vocabulary."""
    depends_on: dict[str, list[str]] = {}
    for param in params:
        if param.dependent_params:
            for dep in param.dependent_params:
                depends_on.setdefault(dep, []).append(param.name)
    return depends_on


def _build_typed_controls_map(
    params: list[WDKParameter],
) -> dict[str, list[str]]:
    """Map each parent param to the child params whose vocabulary it controls."""
    controls: dict[str, list[str]] = {}
    for param in params:
        if param.dependent_params:
            controls[param.name] = list(param.dependent_params)
    return controls


@dataclass(frozen=True)
class _VocabFields:
    allowed_values: list[VocabOption] | None = None
    allowed_values_tree: str | None = None
    allowed_values_note: str | None = None


_VOCAB_TRUNCATION_NOTE = (
    f"Showing first {_MAX_VOCAB_ENTRIES} of many values (list truncated). "
    "Use the exact value/ID you need; it does not have to appear in this list."
)


def _capped_vocab_fields(options: list[VocabOption]) -> _VocabFields:
    """The wire view of an option list, with a note when the cap hid entries."""
    if not options:
        return _VocabFields()
    note = _VOCAB_TRUNCATION_NOTE if len(options) >= _MAX_VOCAB_ENTRIES else None
    return _VocabFields(allowed_values=options, allowed_values_note=note)


def _format_vocabulary(param: WDKParameter) -> _VocabFields:
    return _format_vocabulary_raw(
        param_name=param.name,
        param_type=param.type,
        vocabulary=param.vocabulary,
    )


def _format_vocabulary_raw(
    *,
    param_name: str,
    param_type: str,
    vocabulary: WDKVocabulary | None,
) -> _VocabFields:
    if param_type == "multi-pick-vocabulary" and isinstance(
        vocabulary, WDKTreeBoxVocabNode
    ):
        tree_lines = render_vocab_tree(vocabulary, max_lines=80)
        if tree_lines:
            tree_text = "\n".join(tree_lines)
            truncated = any("use query=" in line for line in tree_lines)
            suffix = "\n(Pass a parent node to auto-select all its children)"
            if truncated:
                suffix += (
                    f"\nNote: tree truncated; use get_parameter_options("
                    f"search_name='<search>', parameter_id='{param_name}', "
                    f"query='<keyword>') to see values for a specific category."
                )
            return _VocabFields(allowed_values_tree=tree_text + suffix)
    elif vocabulary is not None:
        return _capped_vocab_fields(allowed_values(vocabulary))

    return _VocabFields()


def format_typed_param(
    param: WDKParameter,
    depends_on: dict[str, list[str]],
    controls: dict[str, list[str]],
    applied_context: dict[str, ParamValue] | None = None,
    parent_defaults: dict[str, str] | None = None,
    phyletic_options: list[VocabOption] | None = None,
) -> ParameterInfo:
    """Format one typed WDK parameter for the model.

    The note names the parent values the vocabulary was fetched under.
    ``phyletic_options`` is the clade tree a phyletic species list takes.
    """
    name = param.name
    help_text = param.help or ""
    if name == "profile_pattern":
        help_text = _PROFILE_PATTERN_HELP
    if phyletic_options is not None:
        help_text = "\n".join(filter(None, (help_text, _PHYLETIC_LIST_HELP)))

    if is_upload_sentinel_vocabulary(param.vocabulary):
        vocab = _VocabFields(allowed_values_note=UPLOAD_SENTINEL_NOTE)
        leaves: list[VocabOption] = []
    elif phyletic_options is not None:
        # The tree is the list's only vocabulary, so it must reach the wire through
        # ``allowed_values``: ``vocab_leaves`` is excluded from serialization.
        vocab = _capped_vocab_fields(
            dedupe_options(phyletic_options)[:_MAX_VOCAB_ENTRIES]
        )
        leaves = phyletic_options
    else:
        vocab = _format_vocabulary(param)
        leaves = flatten_vocab(param.vocabulary)

    note: str | None = None
    vocab_depends_on: list[str] | None = None
    if name in depends_on:
        parents = depends_on[name]
        vocab_depends_on = parents
        context = applied_context or {}
        applied = {p: context[p] for p in parents if p in context}
        if applied:
            shown = ", ".join(f"{p}={v.to_wire()}" for p, v in sorted(applied.items()))
            note = (
                f"The allowed values for this param change based on the value of "
                f"{', '.join(parents)}. The values below are the vocabulary under "
                f"{shown} -- the values already bound for this search. A different "
                f"parent value yields a DIFFERENT list, so do not conclude a value "
                f"does not exist without re-reading under the parent you mean."
            )
        else:
            defaults = parent_defaults or {}
            used = {p: defaults[p] for p in parents if defaults.get(p)}
            under = (
                ", ".join(f"{p}={v}" for p, v in sorted(used.items()))
                if used
                else "the search defaults"
            )
            note = (
                f"The allowed values for this param change based on the value of "
                f"{', '.join(parents)}. No parent value was supplied, so the values "
                f"below are the vocabulary under {under}. A different parent value "
                f"yields a DIFFERENT list. Re-read with "
                f"context_values={{'{parents[0]}': '<your chosen value>'}} before "
                f"concluding that any value does or does not exist."
            )

    return ParameterInfo(
        name=name,
        display_name=param.display_name or name,
        type=param.type,
        required=not param.allow_empty_value or param.min_selected_count >= 1,
        is_visible=param.is_visible,
        help=help_text,
        value_format=_value_format(param.type),
        default_value=param.initial_display_value,
        is_number=param.is_number,
        min=param.min,
        max=param.max,
        allowed_values=vocab.allowed_values,
        allowed_values_tree=vocab.allowed_values_tree,
        allowed_values_note=vocab.allowed_values_note,
        controls_vocab_of=controls.get(name),
        vocab_depends_on=vocab_depends_on,
        note=note,
        filter_fields=filter_fields_for(param),
        # Always flattened, because ``allowed_values`` is capped and can omit a value.
        vocab_leaves=leaves,
    )


_MAX_FILTER_FIELD_VALUES = 12


def filter_fields_for(param: WDKParameter) -> list[FilterFieldInfo]:
    """Return the leaf ontology terms of a filter param with their valid values.

    Category nodes carry no ``type`` and are not selectable, so they are skipped.
    """
    if param.type != "filter":
        return []
    values = param.values or {}
    return [
        FilterFieldInfo(
            term=term.term,
            display=term.display or term.term,
            type=term.type,
            is_range=term.is_range,
            values=(values.get(term.term) or [])[:_MAX_FILTER_FIELD_VALUES],
        )
        for term in param.ontology
        if term.type is not None
    ]


def format_normalized_param_info(
    specs: dict[str, ParamSpecNormalized],
) -> list[ParameterInfo]:
    depends_on: dict[str, list[str]] = {}
    controls: dict[str, list[str]] = {}
    for parent_name, parent_spec in specs.items():
        for child_name in parent_spec.dependent_params:
            depends_on.setdefault(child_name, []).append(parent_name)
            controls.setdefault(parent_name, []).append(child_name)

    return [
        _format_normalized_one(spec, depends_on, controls)
        for name, spec in specs.items()
        if name not in PHYLETIC_MAP_PARAMS
    ]


def _format_normalized_one(
    spec: ParamSpecNormalized,
    depends_on: dict[str, list[str]],
    controls: dict[str, list[str]],
) -> ParameterInfo:
    vocab = _format_vocabulary_raw(
        param_name=spec.name,
        param_type=spec.param_type,
        vocabulary=spec.vocabulary,
    )
    is_required = not spec.allow_empty_value or (
        spec.min_selected_count is not None and spec.min_selected_count >= 1
    )
    return ParameterInfo(
        name=spec.name,
        display_name=spec.name,
        type=spec.param_type,
        required=is_required,
        is_visible=spec.is_visible,
        help=spec.help or "",
        value_format=_value_format(spec.param_type),
        default_value=spec.initial_display_value,
        is_number=spec.is_number,
        min=spec.min,
        max=spec.max,
        allowed_values=vocab.allowed_values,
        allowed_values_tree=vocab.allowed_values_tree,
        allowed_values_note=vocab.allowed_values_note,
        controls_vocab_of=controls.get(spec.name),
        vocab_depends_on=depends_on.get(spec.name),
    )


def phyletic_options_for(
    params: list[WDKParameter], parameter_id: str, query: str | None
) -> list[VocabOption] | None:
    """The clade tree one phyletic species list takes, narrowed by the query.

    The two lists carry no WDK vocabulary of their own, so a read of either
    shows the tree instead. ``None`` for any other parameter.
    """
    if parameter_id not in PHYLETIC_LIST_PARAMS:
        return None
    tree = phyletic_tree_of(params)
    if tree is None:
        return None
    return filter_vocab_options(tree.labels(), query)


def filter_vocab_options(
    options: list[VocabOption], query: str | None
) -> list[VocabOption]:
    """Keep the options whose code or label contains the query, ignoring case."""
    if not query:
        return options
    needle = query.lower()
    return [
        o for o in options if needle in o.value.lower() or needle in o.display.lower()
    ]


def format_param_info_typed(params: list[WDKParameter]) -> list[ParameterInfo]:
    """Format typed WDK parameters for the model. Phyletic structural params are dropped."""
    depends_on = _build_typed_dependency_map(params)
    controls = _build_typed_controls_map(params)
    tree = phyletic_tree_of(params)
    labels = tree.labels() if tree is not None else None
    return [
        format_typed_param(
            p,
            depends_on,
            controls,
            phyletic_options=labels if p.name in PHYLETIC_LIST_PARAMS else None,
        )
        for p in params
        if p.name not in PHYLETIC_MAP_PARAMS
    ]
