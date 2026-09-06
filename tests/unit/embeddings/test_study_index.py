"""The text a study is indexed by."""

from __future__ import annotations

from veupathdb.eda.models import EdaStudyOverview

from veupathdb_mcp.embeddings.study_index import (
    DESCRIPTION_LIMIT,
    STUDY_INDEX_ID,
    study_enriched_text,
)


def _study(
    *,
    dataset_id: str,
    display: str,
    short: str | None = None,
    description: str | None = None,
) -> EdaStudyOverview:
    return EdaStudyOverview(
        id=dataset_id.replace("DS_", "STUDY_"),
        dataset_id=dataset_id,
        sha1hash="h",
        source_type="curated",
        display_name=display,
        short_display_name=short,
        description=description,
    )


def test_the_enriched_text_joins_the_three_name_fields() -> None:
    text = study_enriched_text(
        _study(
            dataset_id="DS_1",
            display="Heat shock response in sensitive mutants",
            short="Heat shock",
            description="<b>General Description:</b> Illumina sequencing",
        )
    )
    assert "Heat shock response in sensitive mutants" in text
    assert "Heat shock" in text
    assert "Illumina sequencing" in text
    assert "<b>" not in text


def test_a_study_with_no_short_name_and_no_description_still_has_text() -> None:
    text = study_enriched_text(_study(dataset_id="DS_1", display="Only a name"))
    assert text == "Only a name"


def test_a_short_name_equal_to_the_display_name_is_not_repeated() -> None:
    text = study_enriched_text(_study(dataset_id="DS_1", display="Same", short="Same"))
    assert text == "Same"


def test_a_long_description_is_cut_at_the_bound_and_the_names_survive() -> None:
    names = "Malaria host response Host response"
    text = study_enriched_text(
        _study(
            dataset_id="DS_1",
            display="Malaria host response",
            short="Host response",
            description="d" * 24820,
        )
    )
    assert DESCRIPTION_LIMIT == 2000
    assert text == f"{names} {'d' * 2000}"
    assert len(text) == len(names) + 1 + 2000


def test_a_description_under_the_bound_is_unchanged() -> None:
    text = study_enriched_text(
        _study(dataset_id="DS_1", display="Name", description="short abstract")
    )
    assert text == "Name short abstract"


def test_one_index_serves_every_site() -> None:
    """The EDA service answers with the portal's catalog on every site."""
    assert STUDY_INDEX_ID == "eda-studies"
