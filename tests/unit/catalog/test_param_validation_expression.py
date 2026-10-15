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

from veupathdb_mcp.catalog import param_validation

from .conftest import no_dependent_refresh, validation_callbacks, wdk_search_response

_CTX = SearchContext(
    site_id="orthomcl", record_type="group", search_name="GroupsByPhyleticPattern"
)


def _tree() -> PhyleticTree:
    return PhyleticTree.from_taxa(
        [
            TaxonEntry(id="2", parent_id=None, code="HAEM", label="Haemosporida"),
            TaxonEntry(id="3", parent_id="2", code="pfal", label="P. falciparum 3D7"),
            TaxonEntry(id="4", parent_id="2", code="pfag", label="P. falciparum 7G8"),
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
    validated = await _validate("pfal >= 1t and pfag+HAEM <= 1t")

    assert validated.params["phyletic_expression"] == StringValue(
        value="pfal>=1T AND pfag+HAEM<=1T"
    )


async def test_a_unit_every_group_meets_is_refused() -> None:
    with pytest.raises(ValidationError, match="states no constraint"):
        await _validate("pfal>=1T AND pfag<=1T")
