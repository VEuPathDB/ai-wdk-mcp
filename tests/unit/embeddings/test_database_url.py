"""The database address is the one DATABASE_URL names, or the one the Postgres settings build."""

import pytest

from veupathdb_mcp.embeddings.settings import EmbeddingSettings

_POSTGRES = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", *_POSTGRES):
        monkeypatch.delenv(name, raising=False)


def _postgres(monkeypatch: pytest.MonkeyPatch, value: str = "s3cret") -> None:
    monkeypatch.setenv("POSTGRES_HOST", "pathfinder-db")
    monkeypatch.setenv("POSTGRES_USER", "pathfinder")
    monkeypatch.setenv("POSTGRES_PASSWORD", value)
    monkeypatch.setenv("POSTGRES_DB", "pathfinder")


def test_the_postgres_settings_build_the_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _postgres(monkeypatch)

    assert EmbeddingSettings().database_url == (
        "postgresql+asyncpg://pathfinder:s3cret@pathfinder-db:5432/pathfinder"
    )


def test_a_password_with_reserved_characters_is_escaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _postgres(monkeypatch, value="p@ss:w/rd#1")
    monkeypatch.setenv("POSTGRES_PORT", "6543")

    assert EmbeddingSettings().database_url == (
        "postgresql+asyncpg://pathfinder:p%40ss%3Aw%2Frd%231@pathfinder-db:6543/pathfinder"
    )


def test_a_database_url_is_kept_as_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")

    assert EmbeddingSettings().database_url == "postgresql+asyncpg://u:p@h:5432/d"


def test_no_address_and_no_password_leave_the_address_empty() -> None:
    assert EmbeddingSettings().database_url == ""


def test_validating_the_built_settings_again_keeps_the_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _postgres(monkeypatch)
    settings = EmbeddingSettings()

    assert EmbeddingSettings.model_validate(settings).database_url == (
        settings.database_url
    )
    assert EmbeddingSettings(database_url=settings.database_url).database_url == (
        settings.database_url
    )


def test_a_database_url_and_a_password_together_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _postgres(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")

    with pytest.raises(ValueError, match="DATABASE_URL or POSTGRES_PASSWORD, not both"):
        EmbeddingSettings()


@pytest.mark.parametrize("missing", ["POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_DB"])
def test_a_password_without_the_rest_names_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _postgres(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(ValueError, match=f"{missing} is not set"):
        EmbeddingSettings()


def test_the_password_stays_out_of_the_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _postgres(monkeypatch)

    assert "s3cret" not in repr(EmbeddingSettings())
