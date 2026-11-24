from __future__ import annotations

from veupathdb.testing.wdk_fixtures import load_recorded
from veupathdb.wdk import WDKParameter, WDKSearchResponse

from veupathdb_mcp.catalog.search_inspection import VocabNarrowing, _filter_vocab


def _assay() -> WDKParameter:
    body = load_recorded("search_genes_by_mass_spec").json_body()
    search = WDKSearchResponse.model_validate(body).search_data
    [assay] = [p for p in search.parameters or [] if p.name == "ms_assay"]
    return assay


def test_assays_under_four_organisms_are_not_one_name() -> None:
    _, lookup = _filter_vocab(_assay(), VocabNarrowing(query="female gametocytes"))

    assert lookup is not None
    assert lookup.same_named == []
    assert "female gametocytes_Plasmodium falciparum 3D7" in [
        value for match in lookup.matches for value in match.values
    ]
