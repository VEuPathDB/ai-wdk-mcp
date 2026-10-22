"""Every recipe and example the expression help states passes the served validator
and selects the groups its words describe."""

from __future__ import annotations

import re

import pytest
from pydantic import BaseModel, ConfigDict
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    ParamValue,
    PhyleticExpression,
    PhyleticTree,
    StringValue,
)
from veupathdb.errors import ValidationError
from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKAnswer, WDKStringParam, ortho_taxonomy_of

from veupathdb_mcp.catalog import param_validation
from veupathdb_mcp.catalog.param_formatting import (
    ParamDependencies,
    format_typed_param,
)

from .conftest import no_dependent_refresh, validation_callbacks, wdk_search_response

_CTX = SearchContext(
    site_id="orthomcl", record_type="group", search_name="GroupsByPhyleticPattern"
)

_TREE: PhyleticTree | None = ortho_taxonomy_of(
    WDKAnswer.model_validate(load_recorded("orthomcl_taxonomy").body)
)


def _tree() -> PhyleticTree:
    assert _TREE is not None
    return _TREE


def _help() -> str:
    text = format_typed_param(
        WDKStringParam(name="phyletic_expression", help="Phyletic Pattern Expression"),
        ParamDependencies(),
    ).help
    return " ".join(text.split())


class _Instance(BaseModel):
    model_config = ConfigDict(frozen=True)

    recipe: str
    expression: str
    selects: tuple[dict[str, int], ...]
    rejects: tuple[dict[str, int], ...]


_FIRM = {"bant": 1, "bsub": 1, "cper": 1, "lmon": 1}
_CILI = {"ptet": 1, "tetr": 1}

_RECIPES = (
    _Instance(
        recipe="presence in every genome L=NT",
        expression="FIRM=4T",
        selects=(_FIRM, {**_FIRM, "bant": 3}),
        rejects=({"bant": 1, "bsub": 1, "cper": 1}, {}),
    ),
    _Instance(
        recipe="in at least p percent L>=ceil(pN/100)T",
        expression="FIRM>=2T",
        selects=({"bant": 1, "cper": 2}, _FIRM),
        rejects=({"bant": 3}, {"ptet": 1}),
    ),
    _Instance(
        recipe="in some but not all L>=1T AND L<NT",
        expression="FIRM>=1T AND FIRM<4T",
        selects=({"bant": 1}, {"bant": 1, "bsub": 2, "cper": 1}),
        rejects=(_FIRM, {"ptet": 1}),
    ),
    _Instance(
        recipe="absence L=0T",
        expression="FIRM=0T",
        selects=({"ptet": 1}, {}),
        rejects=({"lmon": 1},),
    ),
    _Instance(
        recipe="X AND L<=(N-k)T OR X AND L=0T",
        expression="CILI=2T AND FIRM<=1T OR CILI=2T AND FIRM=0T",
        selects=(_CILI, {**_CILI, "bant": 2}),
        rejects=(
            {**_CILI, "bant": 1, "bsub": 1},
            {"tetr": 1},
            {"tetr": 2},
            {"bant": 1},
            {"tetr": 1, "lmon": 1},
            {"tetr": 2, "lmon": 1},
        ),
    ),
    _Instance(
        recipe="absence from all N genomes is X AND L=0T",
        expression="CILI=2T AND FIRM=0T",
        selects=(_CILI, {"ptet": 2, "tetr": 1, "nmen": 1}),
        rejects=({**_CILI, "lmon": 1}, {"ptet": 1}),
    ),
    _Instance(
        recipe="L<=(N-k)T OR L=0T when there are none",
        expression="FIRM<=1T OR FIRM=0T",
        selects=({"ptet": 1}, {"lmon": 4}),
        rejects=({"bant": 1, "bsub": 1},),
    ),
    _Instance(
        recipe="one unit S>=ceil(k/2)T per species S of k genomes, joined with AND",
        expression="cpia+cpib+cpar>=2T AND cmel+cmtu>=1T",
        selects=(
            {"cpia": 1, "cpar": 1, "cmtu": 1},
            {"cpia": 1, "cpib": 1, "cpar": 1, "cmtu": 1},
            {"cpia": 1, "cpib": 1, "cpar": 1, "cmel": 1, "cmtu": 1},
        ),
        rejects=(
            {"cpia": 1, "cmel": 1, "cmtu": 1},
            {"cpia": 1, "cpib": 1},
            {"cpia": 2, "cmel": 1},
            {"cpib": 2, "cmtu": 1},
        ),
    ),
    _Instance(
        recipe="Single copy, one protein in every genome: L=NT AND L=N",
        expression="FIRM=4T AND FIRM=4",
        selects=(_FIRM,),
        rejects=({**_FIRM, "bant": 2}, {"bant": 1, "bsub": 1, "cper": 2}),
    ),
    _Instance(
        recipe="L1>=c*N1 AND L1<(c+1)*N1 AND L2>=r*c*N2, the bands joined with OR",
        expression="CILI>=2 AND CILI<4 AND PROB>=4 OR CILI>=4 AND CILI<6 AND PROB>=8",
        selects=(
            {**_CILI, "nmen": 2, "rsol": 2},
            {**_CILI, "nmen": 3, "rsol": 3},
            {"tetr": 2, "nmen": 1, "rsol": 3},
            {"ptet": 2, "tetr": 1, "nmen": 4},
            {"tetr": 3, "nmen": 1, "rsol": 3},
            {"ptet": 3, "tetr": 1, "nmen": 8},
            {"tetr": 4, "nmen": 5, "rsol": 4},
            {"ptet": 5, "nmen": 8},
        ),
        rejects=(
            {**_CILI, "nmen": 1, "rsol": 2},
            {"tetr": 1, "nmen": 1, "rsol": 3},
            {"tetr": 1, "nmen": 8},
            {"ptet": 2, "tetr": 2, "nmen": 7},
            {"ptet": 1, "tetr": 3},
            {"ptet": 1, "tetr": 3, "nmen": 1, "rsol": 3},
            {"ptet": 6, "nmen": 20},
        ),
    ),
    _Instance(
        recipe="B=0 AND A>=1 OR B=1 AND A>=2 OR ... OR B=K AND A>=K+1",
        expression="tetr=0 AND ptet>=1 OR tetr=1 AND ptet>=2 OR tetr=2 AND ptet>=3",
        selects=(
            {"ptet": 1},
            {"ptet": 2},
            {"ptet": 3},
            {"ptet": 2, "tetr": 1},
            {"ptet": 3, "tetr": 1},
            {"ptet": 3, "tetr": 2},
            {"ptet": 4, "tetr": 2},
        ),
        rejects=(
            {"ptet": 1, "tetr": 1},
            {"ptet": 2, "tetr": 2},
            {"ptet": 3, "tetr": 3},
            {"tetr": 1},
            {"bant": 1},
        ),
    ),
)


def _outside(clade: str) -> str:
    tree = _tree()
    return "+".join(sorted(tree.genomes_under(["ALL"]) - tree.genomes_under([clade])))


_ONLY_IN_A_CLADE = (
    _Instance(
        recipe="L>=1T AND C=0T",
        expression=f"CILI>=1T AND {_outside('CILI')}=0T",
        selects=({"ptet": 1}, {"ptet": 3, "tetr": 1}),
        rejects=(
            {"ptet": 1, "bant": 1},
            {"tetr": 1, "nmen": 4},
            {"bant": 1},
            {},
        ),
    ),
    _Instance(
        recipe="L>=1T AND X=0T",
        expression="CILI>=1T AND FIRM=0T",
        selects=({"ptet": 1}, {"ptet": 1, "tetr": 2, "nmen": 1}),
        rejects=({"ptet": 1, "lmon": 1}, {"bant": 1}, {}),
    ),
)

_EXAMPLE_CODES = {
    "a": "atum",
    "b": "bdia",
    "c": "bant",
    "d": "bsub",
    "e": "cper",
    "f": "lmon",
}


def _example() -> _Instance:
    found = re.search(r"Example, [^:]+: (.+)\.$", _help())
    assert found is not None
    return _Instance(
        recipe=found[1],
        expression=re.sub(r"\b[a-f]\b", lambda m: _EXAMPLE_CODES[m[0]], found[1]),
        selects=({"atum": 1, "bdia": 2}, {"atum": 1, "bdia": 1, "lmon": 3}),
        rejects=(
            {"atum": 1, "bdia": 1, "bant": 1, "bsub": 1},
            {"atum": 1},
            {"lmon": 1},
            {"atum": 1, "bant": 1},
            {"atum": 2, "lmon": 1},
            {"bdia": 1, "lmon": 1},
            {"bdia": 2, "lmon": 1},
        ),
    )


def _band_zero(
    sentence: str,
    filled: dict[str, str],
    selects: tuple[dict[str, int], ...],
    rejects: tuple[dict[str, int], ...],
) -> _Instance:
    help_text = _help()
    form = re.search(sentence, help_text)
    condition = re.search(r"with Y the condition (\S+),", help_text)
    assert form is not None
    assert condition is not None
    written = form[1].replace("Y", condition[1])
    return _Instance(
        recipe=form[1],
        expression=re.sub(r"\b(L1|N1|L2)\b", lambda m: filled[m[0]], written),
        selects=selects,
        rejects=rejects,
    )


_FROM_HELP = (
    _example(),
    _band_zero(
        r"Band c=0, under N1 proteins in L1, is (.+?), with Y",
        {"L1": "CILI", "N1": "2", "L2": "PROB"},
        selects=(
            {"nmen": 1},
            {"rsol": 2},
            {"ptet": 1, "nmen": 1},
            {"tetr": 1, "rsol": 1},
            {"ptet": 1, "rsol": 3},
        ),
        rejects=(
            {**_CILI, "nmen": 3},
            {"tetr": 2, "rsol": 1},
            {"ptet": 1},
            {"bant": 1},
        ),
    ),
    _band_zero(
        r"When N1 is 1, band c=0 is (.+?) alone\.",
        {"L1": "tetr", "N1": "1", "L2": "PROB"},
        selects=({"nmen": 1}, {"ptet": 1, "rsol": 3}),
        rejects=({"tetr": 1, "nmen": 3}, {"ptet": 1}),
    ),
)

_ALL = (*_RECIPES, *_ONLY_IN_A_CLADE, *_FROM_HELP)


def test_the_complement_names_every_genome_outside_the_clade_once() -> None:
    unit = PhyleticExpression.parse(_ONLY_IN_A_CLADE[0].expression).units()[1]

    assert len(unit.codes) == len(_tree().genomes_under(["ALL"])) - 2 == 855
    assert {"ptet", "tetr"}.isdisjoint(unit.codes)


def test_band_zero_is_read_from_the_help() -> None:
    assert [instance.expression for instance in _FROM_HELP[1:]] == [
        "CILI<2 AND PROB>=1 OR CILI=0T AND PROB>=1",
        "tetr=0T AND PROB>=1",
    ]


@pytest.fixture(autouse=True)
def _served(monkeypatch: pytest.MonkeyPatch) -> None:
    response = wdk_search_response(
        _CTX.search_name, [WDKStringParam(name="phyletic_expression")]
    )

    async def _details(
        ctx: SearchContext,
        *,
        resolved_record_type: str,
        parameters: dict[str, ParamValue],
    ) -> param_validation.ResolvedSearch:
        del ctx, resolved_record_type, parameters
        return param_validation.ResolvedSearch(response=response, values_were_read=True)

    async def _taxonomy(site_id: str) -> PhyleticTree:
        assert site_id == "orthomcl"
        return _tree()

    monkeypatch.setattr(param_validation, "resolve_search_details", _details)
    monkeypatch.setattr(
        param_validation, "get_refreshed_dependent_params", no_dependent_refresh
    )
    monkeypatch.setattr(param_validation, "ortho_taxonomy", _taxonomy)


async def _validate(expression: str) -> param_validation.ValidatedParams:
    return await param_validation.validate_parameters(
        _CTX,
        parameters={"phyletic_expression": StringValue(value=expression)},
        callbacks=validation_callbacks(),
    )


def test_the_example_is_the_help_s_last_sentence() -> None:
    assert _example().expression == (
        "atum+bdia=2T AND bant+bsub+cper+lmon<=1T "
        "OR atum+bdia=2T AND bant+bsub+cper+lmon=0T"
    )


@pytest.mark.parametrize("instance", _ALL, ids=[r.recipe for r in _ALL])
async def test_the_validator_accepts_each_recipe_as_written(
    instance: _Instance,
) -> None:
    assert instance.recipe in _help()

    validated = await _validate(instance.expression)

    held = StringValue.model_validate(validated.params["phyletic_expression"])
    assert PhyleticExpression.parse(held.value) == PhyleticExpression.parse(
        instance.expression
    )


@pytest.mark.parametrize("instance", _ALL, ids=[r.recipe for r in _ALL])
def test_each_recipe_selects_the_groups_its_words_describe(
    instance: _Instance,
) -> None:
    expression = PhyleticExpression.parse(instance.expression)

    assert [expression.holds_for(group, _tree()) for group in instance.selects] == [
        True
    ] * len(instance.selects)
    assert [expression.holds_for(group, _tree()) for group in instance.rejects] == [
        False
    ] * len(instance.rejects)


@pytest.mark.parametrize(
    ("refused", "named"),
    [
        (
            "tetr<1 AND PROB>=1T OR tetr=0T AND PROB>=1T",
            "When N1 is 1, band c=0 is L1=0T AND Y alone.",
        ),
        ("FIRM<=0T OR FIRM=0T", "absence from at least k, for k below N,"),
    ],
)
async def test_a_recipe_form_the_validator_refuses_has_its_exception_in_the_help(
    refused: str, named: str
) -> None:
    with pytest.raises(ValidationError, match="matches no group"):
        await _validate(refused)

    assert named in _help()
