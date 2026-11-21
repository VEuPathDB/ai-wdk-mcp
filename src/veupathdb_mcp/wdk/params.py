"""The vocabulary a WDK parameter offers, the defaults a form states, and the
wire form of one value.

Pure module. A value is read by the kind its parameter declares.
"""

from collections.abc import Sequence

from pydantic import JsonValue
from veupathdb import JSONObject
from veupathdb.domain.parameters import flatten_vocab, vocab_keys
from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog import read_declared


def extract_vocab_values(params: Sequence[WDKParameter], param_name: str) -> list[str]:
    """Extract the allowed vocabulary values for a named parameter.

    A flat vocabulary yields its terms and a tree box yields its leaf terms,
    in the order the vocabulary lists them. A clade node groups organisms and
    is not a term WDK accepts.
    """
    for p in params:
        if p.name == param_name:
            accepted = vocab_keys(p.vocabulary)
            return [
                option.value
                for option in flatten_vocab(p.vocabulary)
                if option.value in accepted
            ]
    return []


def encode_named_param_value(
    params: Sequence[WDKParameter], name: str, value: JsonValue
) -> JsonValue:
    """The wire form of one named value, for the kind the form declares.

    A form that does not carry the name states no kind, so the value stands as
    the caller wrote it.
    """
    read = read_declared(params, {name: value})
    return read[name].to_wire() if name in read else value


def extract_default_params(params: Sequence[WDKParameter]) -> JSONObject:
    """The default value each parameter of a form offers.

    WDK's ``ParamFormatter.java`` emits ``initialDisplayValue`` (via
    ``JsonKeys.INITIAL_DISPLAY_VALUE``) as the stable value, which is the wire
    form of that parameter's kind.
    """
    return {
        p.name: p.initial_display_value
        for p in params
        if p.name and p.initial_display_value is not None
    }
