"""WDK enrichment parameter encoding helpers.

Pure module (no I/O). Handles vocabulary parameter encoding as JSON
arrays per WDK's ``AbstractEnumParam.convertToTerms()`` requirements,
and extraction of default parameter values from typed WDK parameters.
"""

import json
from collections.abc import Sequence

from veupathdb.json_types import JSONObject
from veupathdb.wdk.wdk_parameters import WDKParameter

# WDK ``EnumParamFormatter.getParamType()`` emits these JSON type strings
# for params extending ``AbstractEnumParam`` (``EnumParam``, ``FlatVocabParam``).
# These are the only param types whose stable values must be JSON arrays
# (via ``AbstractEnumParam.convertToTerms()`` → ``new JSONArray(stableValue)``).
# See ``org.gusdb.wdk.core.api.JsonKeys`` for the constant names
# (SINGLE_VOCAB_PARAM_TYPE and MULTI_VOCAB_PARAM_TYPE).
WDK_VOCAB_PARAM_TYPES = frozenset({"single-pick-vocabulary", "multi-pick-vocabulary"})


def extract_vocab_values(params: Sequence[WDKParameter], param_name: str) -> list[str]:
    """Extract the allowed vocabulary values for a named parameter.

    WDK vocabulary params include a ``vocabulary`` field, a list of
    ``[value, display, null]`` triples.  Returns the ``value`` strings
    (first element of each triple).

    Returns an empty list if the parameter is not found or has no vocabulary.
    """
    for p in params:
        if p.name != param_name:
            continue
        if not isinstance(p.vocabulary, list):
            return []
        return [entry.term for entry in p.vocabulary]
    return []


def encode_vocab_value(value: str) -> str:
    """Ensure a vocabulary param value is a JSON array string.

    ``AbstractEnumParam.convertToTerms()`` calls
    ``new JSONArray(stableValue)``, so a plain string is a parse error.
    Multi-pick values already arrive as JSON arrays from WDK; single-pick
    values arrive as plain strings and must be wrapped.
    """
    if value.startswith("["):
        try:
            json.loads(value)
        except json.JSONDecodeError, ValueError:
            pass
        else:
            return value
    return json.dumps([value])


def encode_vocab_params(
    params: JSONObject,
    wdk_params: Sequence[WDKParameter],
) -> JSONObject:
    """Encode vocabulary param values as JSON arrays.

    WDK's ``AbstractEnumParam.convertToTerms()`` requires all
    ``single-pick-vocabulary`` and ``multi-pick-vocabulary`` param values
    to be JSON-encoded arrays.  This function ensures that encoding is
    applied **after** merging defaults with user params, so user-supplied
    plain strings don't bypass the encoding.

    Params whose type is not in the WDK parameter list, or whose type is
    not a vocabulary type, are returned unchanged.
    """
    type_map = {p.name: p.type for p in wdk_params if p.name}
    if not type_map:
        return params

    encoded: JSONObject = {}
    for name, value in params.items():
        ptype = type_map.get(name, "")
        if ptype in WDK_VOCAB_PARAM_TYPES and isinstance(value, str):
            encoded[name] = encode_vocab_value(value)
        else:
            encoded[name] = value
    return encoded


def extract_default_params(params: Sequence[WDKParameter]) -> JSONObject:
    """Extract parameter names and default values from typed WDK parameters.

    WDK's ``ParamFormatter.java`` emits ``initialDisplayValue`` (via
    ``JsonKeys.INITIAL_DISPLAY_VALUE``) as the stable default value.

    Vocabulary params (``single-pick-vocabulary``, ``multi-pick-vocabulary``)
    are encoded as JSON arrays per ``AbstractEnumParam.convertToTerms()``.
    """
    defaults: JSONObject = {}
    for p in params:
        if not p.name or p.initial_display_value is None:
            continue

        value = p.initial_display_value

        # Vocab params must be JSON arrays for convertToTerms().
        if p.type in WDK_VOCAB_PARAM_TYPES:
            value = encode_vocab_value(value)

        defaults[p.name] = value
    return defaults
