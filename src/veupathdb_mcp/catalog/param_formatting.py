"""Pure formatting of WDK parameter specs into AI-facing info objects."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, ValidationError, model_validator
from veupathdb.domain.parameters import (
    PHYLETIC_LIST_PARAMS,
    PHYLETIC_MAP_PARAMS,
    ParamKind,
    ParamValue,
    VocabOption,
    WDKTreeBoxVocabNode,
    dedupe_options,
)
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKBaseParameter, WDKParameter, phyletic_tree_of

from veupathdb_mcp.catalog.eda_backed import (
    UPLOAD_SENTINEL_NOTE,
    is_upload_sentinel_vocabulary,
)
from veupathdb_mcp.catalog.shortlist import shortlist_values
from veupathdb_mcp.catalog.vocab_lookup import VocabLookup
from veupathdb_mcp.catalog.vocab_rendering import (
    entries_of,
    prompts_of,
    render_vocab_tree,
    vocab_options,
)

RADIO_OFF = "N/A"
"""The value a free-text half takes when it states nothing. An empty value is refused."""

# The prompt a site prints in a free-text box, for example "(Example: chr22)".
_EXAMPLE_PROMPT = re.compile(r"\(example:.*\)", re.IGNORECASE | re.DOTALL)

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
    "filter": (
        '{"type": "filter", "filters": [{"field": "<member facet>", "value": '
        '["<member>", "..."]}, {"field": "<range facet>", "value": {"min": <n>, '
        '"max": <n>}}]}; a range leaves out the bound it does not state. '
        'Shorthand: "<member facet>=<m1>,<m2>", "<range facet><=<n>", '
        '"<range facet>>=<n>" or "<range facet>=<lo>..<hi>"'
    ),
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
    values_total: int | None = None


class ParameterInfo(CamelModel):
    """Formatted WDK parameter info for AI tool consumption."""

    kind: Literal["parameter_info"] = "parameter_info"
    name: str
    display_name: str
    type: str
    required: bool
    is_visible: bool
    # WDK marks a parameter only the site sets with ``isReadOnly``.
    is_read_only: bool = False
    # WDK reports numeric bounds as ``type: "string"`` with ``isNumber: true``.
    is_number: bool = False
    # WDK marks the search's organism parameter with ``properties.organismProperties``.
    organism_param: bool = False
    help: str
    value_format: str
    default_value: str | None = None
    min: float | None = None
    max: float | None = None
    allowed_values: list[VocabOption] | None = None
    # The count the shown list was cut from. None when the list travels whole.
    allowed_values_total: int | None = None
    allowed_values_tree: str | None = None
    allowed_values_note: str | None = None
    # The shown entries that carry the request's words. None when no request ranked the read.
    allowed_values_from_request: int | None = None
    # The terms of the entries the site ships as a prompt, left out of every list.
    prompt_values: list[str] = Field(default_factory=list)
    # The phrasings a query read, when one narrowed the vocabulary.
    vocab_lookup: VocabLookup | None = None
    controls_vocab_of: list[str] | None = None
    vocab_depends_on: list[str] | None = None
    note: str | None = None
    filter_fields: list[FilterFieldInfo] = Field(default_factory=list)
    filter_leaves: list[FilterFieldInfo] = Field(default_factory=list, exclude=True)
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

    def facets(self) -> list[FilterFieldInfo]:
        """Every facet with every value the site sent, else the shown view."""
        return self.filter_leaves or self.filter_fields

    def is_placeholder(self, value: str) -> bool:
        """Whether a value is the site's prompt text, a prompt entry of the
        vocabulary, or the radio off value.

        Any other term the vocabulary offers is a value, whatever it reads.
        """
        if value in self.prompt_values:
            return True
        if any(option.value == value for option in self.vocabulary()):
            return False
        text = value.strip()
        return text.casefold() == RADIO_OFF.casefold() or bool(
            _EXAMPLE_PROMPT.fullmatch(text)
        )


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


@dataclass(frozen=True, slots=True)
class ParamDependencies:
    """Which parameters' vocabularies each parameter controls, both ways."""

    # Each child parameter, with the parents that determine its vocabulary.
    depends_on: Mapping[str, list[str]] = field(default_factory=dict)
    # Each parent parameter, with the children whose vocabulary it controls.
    controls: Mapping[str, list[str]] = field(default_factory=dict)


def param_dependencies(params: Sequence[WDKBaseParameter]) -> ParamDependencies:
    """The dependency links the parameters of one search declare."""
    depends_on: dict[str, list[str]] = {}
    controls: dict[str, list[str]] = {}
    for param in params:
        if param.dependent_params:
            controls[param.name] = list(param.dependent_params)
            for dep in param.dependent_params:
                depends_on.setdefault(dep, []).append(param.name)
    return ParamDependencies(depends_on=depends_on, controls=controls)


@dataclass(frozen=True)
class _VocabFields:
    allowed_values: list[VocabOption] | None = None
    allowed_values_total: int | None = None
    allowed_values_tree: str | None = None
    allowed_values_note: str | None = None
    allowed_values_from_request: int | None = None


# The entries a whole vocabulary shows; a query reaches the rest.
_MAX_VOCAB_ENTRIES = 50
# The entries a query-narrowed vocabulary shows. A narrowed list travels whole below it.
_MAX_NARROWED_ENTRIES = 300


def _from_request(shown: list[VocabOption], lookup: VocabLookup | None) -> int | None:
    """The shown entries that carry the request's words, when the request ranked."""
    if lookup is None or not lookup.request_terms:
        return None
    carried = set(lookup.request_values())
    return sum(option.value in carried for option in shown)


def _request_note(held: int, lookup: VocabLookup) -> str:
    words = ", ".join(f"'{term}'" for term in lookup.request_terms)
    total = len(lookup.request_values())
    if not total:
        return f" No entry the query kept carries the request's words {words}."
    if held == total:
        return (
            f" The list holds all {total} entries whose labels carry the request's "
            f"words {words}, first."
        )
    return (
        f" The list holds {held} of the {total} entries whose labels carry the "
        f"request's words {words}."
    )


def _capped_vocab_fields(
    options: list[VocabOption], lookup: VocabLookup | None
) -> _VocabFields:
    """The wire view of an option list, with the total and a note when cut.

    A narrowed list travels whole up to the larger cap.
    """
    if not options:
        return _VocabFields()
    cap = _MAX_VOCAB_ENTRIES if lookup is None else _MAX_NARROWED_ENTRIES
    shown = options[:cap]
    held = _from_request(shown, lookup)
    if len(options) <= cap:
        return _VocabFields(allowed_values=shown, allowed_values_from_request=held)
    note = (
        f"Showing {cap} of {len(options)} values (list truncated). "
        "Use the exact value/ID you need; it does not have to appear in this list."
    )
    if held is not None and lookup is not None:
        note += _request_note(held, lookup)
    return _VocabFields(
        allowed_values=shown,
        allowed_values_total=len(options),
        allowed_values_note=note,
        allowed_values_from_request=held,
    )


def _format_vocabulary(param: WDKParameter, lookup: VocabLookup | None) -> _VocabFields:
    vocabulary = param.vocabulary
    if param.type == "multi-pick-vocabulary" and isinstance(
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
                    f"search_name='<search>', parameter_id='{param.name}', "
                    f"query='<keyword>') to see values for a specific category."
                )
            return _VocabFields(allowed_values_tree=tree_text + suffix)
    elif vocabulary is not None:
        return _capped_vocab_fields(vocab_options(vocabulary), lookup)

    return _VocabFields()


def format_typed_param(
    param: WDKParameter,
    dependencies: ParamDependencies,
    applied_context: dict[str, ParamValue] | None = None,
    parent_defaults: dict[str, str] | None = None,
    phyletic_options: list[VocabOption] | None = None,
    lookup: VocabLookup | None = None,
) -> ParameterInfo:
    """Format one typed WDK parameter for the model.

    The note names the parent values the vocabulary was fetched under.
    ``phyletic_options`` is the clade tree a phyletic species list takes.
    ``lookup`` is the query that narrowed the vocabulary, if one did.
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
        vocab = _capped_vocab_fields(dedupe_options(phyletic_options), lookup)
        leaves = phyletic_options
    else:
        vocab = _format_vocabulary(param, lookup)
        leaves = entries_of(param.vocabulary)

    note: str | None = None
    vocab_depends_on: list[str] | None = None
    if name in dependencies.depends_on:
        parents = dependencies.depends_on[name]
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

    facets = filter_fields_for(param)
    return ParameterInfo(
        name=name,
        display_name=param.display_name or name,
        type=param.type,
        required=not param.allow_empty_value or param.min_selected_count >= 1,
        is_visible=param.is_visible,
        is_read_only=param.is_read_only,
        help=help_text,
        value_format=_value_format(param.type),
        default_value=param.initial_display_value,
        is_number=param.is_number,
        organism_param=param.is_organism,
        min=param.min,
        max=param.max,
        allowed_values=vocab.allowed_values,
        allowed_values_total=vocab.allowed_values_total,
        allowed_values_tree=vocab.allowed_values_tree,
        allowed_values_note=vocab.allowed_values_note,
        allowed_values_from_request=vocab.allowed_values_from_request,
        prompt_values=prompts_of(param.vocabulary),
        vocab_lookup=lookup,
        controls_vocab_of=dependencies.controls.get(name),
        vocab_depends_on=vocab_depends_on,
        note=note,
        filter_fields=shown_facets(facets, ""),
        filter_leaves=facets,
        # Always flattened, because ``allowed_values`` is capped and can omit a value.
        vocab_leaves=leaves,
    )


def shown_facets(facets: list[FilterFieldInfo], query: str) -> list[FilterFieldInfo]:
    """Each facet with the values a model reads of it, ranked by ``query``.

    A cut facet names how many values the site sent."""
    shown: list[FilterFieldInfo] = []
    for facet in facets:
        values = shortlist_values(facet.values, query)
        total = len(facet.values) if len(values) < len(facet.values) else None
        shown.append(facet.model_copy(update={"values": values, "values_total": total}))
    return shown


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
            values=values.get(term.term) or [],
        )
        for term in param.ontology
        if term.type is not None
    ]


def phyletic_options_for(
    params: list[WDKParameter], parameter_id: str
) -> list[VocabOption] | None:
    """The clade tree one phyletic species list takes.

    The two lists carry no WDK vocabulary of their own, so a read of either
    shows the tree instead. ``None`` for any other parameter.
    """
    if parameter_id not in PHYLETIC_LIST_PARAMS:
        return None
    tree = phyletic_tree_of(params)
    return None if tree is None else tree.labels()


def format_param_info_typed(params: list[WDKParameter]) -> list[ParameterInfo]:
    """Format typed WDK parameters for the model. Phyletic structural params are dropped."""
    dependencies = param_dependencies(params)
    tree = phyletic_tree_of(params)
    labels = tree.labels() if tree is not None else None
    return [
        format_typed_param(
            p,
            dependencies,
            phyletic_options=labels if p.name in PHYLETIC_LIST_PARAMS else None,
        )
        for p in params
        if p.name not in PHYLETIC_MAP_PARAMS
    ]
