"""The sheet shows a whole small vocabulary, a shortlist of a large one, and says which.

Ranking is lexical on purpose. Embedding a vocabulary takes 21 s for 500 options
and 238 s for 5,461 on the API container, and the sheet is built inside a tool
call the model waits on.
"""

from __future__ import annotations

from veupathdb.domain.parameters import VocabOption
from veupathdb.wdk import WDKEnumParam

from veupathdb_mcp.catalog.param_formatting import (
    ParameterInfo,
    format_param_info_typed,
)
from veupathdb_mcp.catalog.param_sheet import (
    DIRECT_MAX,
    TOP_K,
    SheetEntry,
    build_sheet,
)

from .conftest import vocab_terms


def _param(
    name: str,
    leaves: list[VocabOption],
    *,
    depends: list[str] | None = None,
    tree: str | None = None,
) -> ParameterInfo:
    return ParameterInfo(
        name=name,
        display_name=name,
        type="multi-pick-vocabulary",
        required=True,
        is_visible=True,
        help="h",
        value_format="",
        vocab_leaves=leaves,
        vocab_depends_on=depends,
        allowed_values_tree=tree,
    )


def _go_terms(count: int) -> list[VocabOption]:
    return [VocabOption(value=f"GO:{i:07d}", display=f"term {i}") for i in range(count)]


def test_a_small_vocabulary_is_shown_whole() -> None:
    leaves = [VocabOption(value=f"v{i}", display=f"v{i}") for i in range(10)]

    [entry] = build_sheet([_param("p", leaves)], query="anything")

    assert len(entry.vocabulary) == 10
    assert entry.vocabulary_total == 10
    assert entry.vocabulary_note is None


def test_a_large_vocabulary_is_shortlisted_and_says_so() -> None:
    leaves = _go_terms(DIRECT_MAX + 500)
    leaves[-1] = VocabOption(value="GO:9999999", display="wanted term")

    [entry] = build_sheet([_param("go_typeahead", leaves)], query="the wanted term")

    assert len(entry.vocabulary) == TOP_K
    assert entry.vocabulary_total == DIRECT_MAX + 500
    assert entry.vocabulary[0].value == "GO:9999999"
    assert "get_parameter_options" in (entry.vocabulary_note or "")
    assert "most relevant to the request by name" in (entry.vocabulary_note or "")


def test_a_named_identifier_is_pinned_even_when_ranking_misses_it() -> None:
    leaves = _go_terms(DIRECT_MAX + 500)

    [entry] = build_sheet([_param("go_typeahead", leaves)], query="GO:0000650 please")

    assert any(o.value == "GO:0000650" for o in entry.vocabulary)


def _domain_families(count: int) -> list[VocabOption]:
    """A typeahead vocabulary, written the way WDK writes one: accession, label."""
    return [
        VocabOption(
            value=f"PF9{i:04d} : InterPro domain {i}",
            display=f"PF9{i:04d} : InterPro domain {i}",
        )
        for i in range(count)
    ]


def _enzyme_classes(count: int) -> list[VocabOption]:
    """An EC typeahead vocabulary, written the way WDK writes one: accession, label."""
    return [
        VocabOption(
            value=f"EC:1.{i} : enzyme class {i}",
            display=f"EC:1.{i} : enzyme class {i}",
        )
        for i in range(count)
    ]


def test_a_named_accession_is_pinned_when_the_label_is_not_written_out() -> None:
    # The label holds none of the request's words, so ranking puts this entry
    # last of 700. Only the pin carries it onto the sheet.
    leaves = _enzyme_classes(700)
    leaves[600] = VocabOption(
        value="EC:2.7.1 : Protein kinase", display="EC:2.7.1 : Protein kinase"
    )

    [entry] = build_sheet(
        [_param("ec_typeahead", leaves)], query="the enzyme class EC:2.7.1"
    )

    assert entry.vocabulary[0].value == "EC:2.7.1 : Protein kinase"


def test_a_short_leading_word_is_not_an_accession_and_is_not_pinned() -> None:
    # Both entries hold a word the request writes and nothing else does, so
    # rarity scores them the same; only the pin can order them.
    leaves = _domain_families(700)
    leaves[100] = VocabOption(value="ABC : Alpha kinase", display="ABC : Alpha kinase")
    leaves[600] = VocabOption(value="PF00069 : Pkinase", display="PF00069 : Pkinase")

    [entry] = build_sheet(
        [_param("domain_typeahead", leaves)], query="InterPro domain ABC PF00069"
    )

    order = [o.value for o in entry.vocabulary]
    # A pinned entry leads whatever its position; the short word earns rank only.
    assert order[0] == "PF00069 : Pkinase"
    assert order[1] == "ABC : Alpha kinase"


def _phyletic_profile() -> list[VocabOption]:
    """A phyletic vocabulary: many Plasmodium entries, one Homo sapiens entry."""
    leaves = [
        VocabOption(value=f"sp{i}", display=f"sp{i} -- organism {i} REF")
        for i in range(700)
    ]
    for i in range(60):
        leaves[i] = VocabOption(
            value=f"pspp{i}", display=f"pspp{i} -- Plasmodium species {i}"
        )
    leaves[650] = VocabOption(value="hsap", display="hsap -- Homo sapiens REF")
    return leaves


def test_a_rare_request_word_outranks_a_common_one() -> None:
    [entry] = build_sheet(
        [_param("excluded_species", _phyletic_profile())],
        query="in Plasmodium, not H. sapiens",
    )

    order = [o.value for o in entry.vocabulary]
    assert "hsap" in order
    assert order[0] == "hsap"
    assert all(order.index("hsap") < order.index(f"pspp{i}") for i in range(60))


def test_a_stopword_in_the_request_ranks_nothing() -> None:
    leaves = _phyletic_profile()
    leaves[5] = VocabOption(value="nross", display="nross -- Notothenia rossii REF")

    [entry] = build_sheet(
        [_param("excluded_species", leaves)], query="in Plasmodium, not H. sapiens"
    )

    order = [o.value for o in entry.vocabulary]
    assert order[0] == "hsap"
    assert order.index("hsap") < order.index("nross")


def test_a_request_word_matches_a_whole_label_word_not_a_fragment() -> None:
    leaves = _phyletic_profile()
    leaves[5] = VocabOption(value="psap", display="psap -- Pseudomonas sapiensis")

    [entry] = build_sheet(
        [_param("excluded_species", leaves)], query="in Plasmodium, not H. sapiens"
    )

    order = [o.value for o in entry.vocabulary]
    assert order[0] == "hsap"
    assert order.index("hsap") < order.index("psap")


def test_shared_words_rank_an_option_above_an_unrelated_one() -> None:
    leaves = _go_terms(300)
    leaves[10] = VocabOption(value="GO:0005515", display="protein binding")
    leaves[20] = VocabOption(value="GO:0016301", display="kinase activity")
    leaves[30] = VocabOption(value="GO:0016772", display="transferase kinase")

    [entry] = build_sheet([_param("go_typeahead", leaves)], query="kinase activity")

    order = [o.value for o in entry.vocabulary]
    assert order.index("GO:0016301") < order.index("GO:0005515")
    # Weights add, so both words beat the one that two labels share, which beats none.
    assert order.index("GO:0016301") < order.index("GO:0016772")
    assert order.index("GO:0016772") < order.index("GO:0005515")


def test_short_query_words_do_not_rank() -> None:
    leaves = _go_terms(300)
    leaves[10] = VocabOption(value="GO:8888888", display="an in of")

    [entry] = build_sheet([_param("go_typeahead", leaves)], query="in an of")

    # Nothing scored, so the vocabulary keeps its original order.
    assert [o.value for o in entry.vocabulary] == [o.value for o in leaves[:TOP_K]]


def test_a_dependent_vocabulary_names_its_parents() -> None:
    leaves = [VocabOption(value="a", display="a")]

    [entry] = build_sheet([_param("child", leaves, depends=["parent"])], query="")

    assert entry.depends_on == ["parent"]
    assert "parent" in (entry.vocabulary_note or "")


def test_a_tree_vocabulary_says_a_parent_selects_its_children() -> None:
    leaves = [VocabOption(value="pfal", display="P. falciparum")]

    [entry] = build_sheet(
        [_param("organism", leaves, tree="Plasmodium\n  P. falciparum")], query=""
    )

    assert entry.is_tree is True
    assert "A parent term selects all of its children." in (entry.vocabulary_note or "")


def test_a_flat_vocabulary_is_not_a_tree() -> None:
    leaves = [VocabOption(value="a", display="a")]

    [entry] = build_sheet([_param("p", leaves)], query="")

    assert entry.is_tree is False


def test_hidden_params_are_not_on_the_sheet() -> None:
    hidden = ParameterInfo(
        name="WebServicesPath",
        display_name="",
        type="string",
        required=True,
        is_visible=False,
        help="",
        value_format="",
        default_value="dflt",
    )

    assert build_sheet([hidden], query="") == []


def _dataset_entry(*pairs: tuple[str, str]) -> SheetEntry:
    param = WDKEnumParam(
        name="eda_dataset_id",
        display_name="User dataset",
        type="single-pick-vocabulary",
        vocabulary=vocab_terms(*pairs),
    )
    entries = build_sheet(format_param_info_typed([param]), query="my phenotype data")
    assert len(entries) == 1
    return entries[0]


def test_the_sheet_offers_no_value_when_the_vocabulary_is_the_sentinel() -> None:
    entry = _dataset_entry(
        ("EDAUD_slI5M0RwIg0Zw", "Upload a Phenotype User Dataset in My Workspace")
    )

    assert entry.vocabulary == []
    assert entry.vocabulary_total == 0
    assert entry.vocabulary_note is not None
    assert "no installed dataset" in entry.vocabulary_note


def test_the_sheet_keeps_a_real_one_dataset_vocabulary() -> None:
    entry = _dataset_entry(("EDAUD_realid", "My RNA-Seq counts"))

    assert [option.value for option in entry.vocabulary] == ["EDAUD_realid"]
    assert entry.vocabulary_note is None
