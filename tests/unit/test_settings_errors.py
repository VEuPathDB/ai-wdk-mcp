import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from veupathdb_mcp.embeddings.settings import EmbeddingSettings
from veupathdb_mcp.research.settings import ResearchSettings
from veupathdb_mcp.settings import McpSettings

_GIVEN = "given-value-7f3a"


@pytest.mark.parametrize(
    ("settings", "field"),
    [
        (McpSettings, "site_catalog_budget_mb"),
        (ResearchSettings, "max_retries"),
        (EmbeddingSettings, "postgres_port"),
    ],
)
def test_a_settings_error_does_not_echo_the_values_it_was_given(
    settings: type[BaseSettings], field: str
) -> None:
    with pytest.raises(ValidationError) as error:
        settings.model_validate({field: _GIVEN})

    assert _GIVEN not in str(error.value)


def test_a_postgres_error_does_not_echo_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "pathfinder")
    monkeypatch.setenv("POSTGRES_DB", "pathfinder")
    monkeypatch.setenv("POSTGRES_PASSWORD", _GIVEN)

    with pytest.raises(ValidationError, match="POSTGRES_HOST is not set") as error:
        EmbeddingSettings()

    assert "input_value" not in str(error.value)
