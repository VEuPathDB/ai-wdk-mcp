"""OrthoMCL answers a malformed phyletic expression with a 500, so the grammar and
the codes are judged before the criterion is accepted."""

from __future__ import annotations

import pytest
from veupathdb.domain import SearchContext
from veupathdb.domain.parameters import (
    ParamValue,
    PhyleticTree,
    StringValue,
    TaxonEntry,
)
from veupathdb.errors import ValidationError
from veupathdb.wdk import WDKStringParam

from veupathdb_mcp.catalog import (
    MAX_EXPRESSION_TERMS,
    MAX_EXPRESSION_WORK,
    PhyleticExpressionTooLargeError,
    param_validation,
)

from .conftest import no_dependent_refresh, validation_callbacks, wdk_search_response

_CTX = SearchContext(
    site_id="orthomcl", record_type="group", search_name="GroupsByPhyleticPattern"
)


def _tree() -> PhyleticTree:
    return PhyleticTree.from_taxa(
        [
            TaxonEntry(
                id="2", parent_id=None, code="HAEM", label="Haemosporida", clade=True
            ),
            TaxonEntry(
                id="3",
                parent_id="2",
                code="pfal",
                label="P. falciparum 3D7",
                clade=False,
            ),
            TaxonEntry(
                id="4",
                parent_id="2",
                code="pfag",
                label="P. falciparum 7G8",
                clade=False,
            ),
            TaxonEntry(
                id="5", parent_id="2", code="pber", label="P. berghei ANKA", clade=False
            ),
        ]
    )


@pytest.fixture(autouse=True)
def _served(monkeypatch: pytest.MonkeyPatch) -> None:
    response = wdk_search_response(
        _CTX.search_name,
        [
            WDKStringParam(
                name="phyletic_expression",
                display_name="Expression",
                initial_display_value="amac+acaq=2T",
            )
        ],
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


async def test_a_malformed_expression_is_refused_with_the_grammar() -> None:
    with pytest.raises(ValidationError) as caught:
        await _validate("(pfag+>=1) AND pfal=1")

    assert "'+' joins two codes" in (caught.value.detail or "")


async def test_a_code_the_taxonomy_lacks_is_refused() -> None:
    with pytest.raises(ValidationError, match="Unknown codes: zzzz"):
        await _validate("pfal>=1T AND zzzz=0T")


async def test_a_valid_expression_is_held_in_the_sites_spelling() -> None:
    validated = await _validate("pfal >= 1t and pfag+pber <= 1t")

    assert validated.params["phyletic_expression"] == StringValue(
        value="pfal>=1T AND pfag+pber<=1T"
    )


async def test_a_unit_every_group_meets_is_refused() -> None:
    with pytest.raises(ValidationError, match="states no constraint"):
        await _validate("pfal>=1T AND pfag<=1T")


def _unread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _taxonomy(site_id: str) -> PhyleticTree:
        raise AssertionError(site_id)

    monkeypatch.setattr(param_validation, "ortho_taxonomy", _taxonomy)


async def test_a_stated_expression_past_the_term_cap_is_refused_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _unread(monkeypatch)

    with pytest.raises(PhyleticExpressionTooLargeError) as caught:
        await _validate(
            " OR ".join(f"pfal={k}" for k in range(MAX_EXPRESSION_TERMS + 1))
        )

    assert (caught.value.limit, caught.value.terms) == (
        "terms",
        MAX_EXPRESSION_TERMS + 1,
    )


async def test_a_stated_expression_of_as_many_terms_as_the_cap_is_held() -> None:
    expression = " OR ".join(f"pfal={k}" for k in range(MAX_EXPRESSION_TERMS))

    validated = await _validate(expression)

    assert validated.params["phyletic_expression"] == StringValue(value=expression)


async def test_a_stated_expression_past_the_work_cap_is_refused_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _unread(monkeypatch)
    term = "pfal+pfag+pber={k} AND pfag+pber={k} AND pfal+pber={k} AND pfal={k}"

    with pytest.raises(PhyleticExpressionTooLargeError) as caught:
        await _validate(" OR ".join(term.format(k=k) for k in range(1500)))

    assert caught.value.limit == "work"
    assert caught.value.work > MAX_EXPRESSION_WORK
