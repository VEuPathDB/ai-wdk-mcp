"""The applications the MCP server admits without a VEuPathDB user."""

import pytest
from pydantic import ValidationError

from veupathdb_mcp.service_tokens import ServiceTokenRegistry

SECRET = "analytics-secret-0123456789abcdefgh"
OTHER_SECRET = "gene-page-secret-0123456789abcdefgh"


class TestServiceTokenRegistry:
    def test_an_empty_setting_matches_nothing(self) -> None:
        registry = ServiceTokenRegistry.parse("")

        assert registry.tokens == ()
        assert registry.application_for(SECRET) is None

    def test_a_configured_secret_names_its_application(self) -> None:
        registry = ServiceTokenRegistry.parse(f"analytics:{SECRET}")

        assert registry.application_for(SECRET) == "analytics"

    def test_an_unknown_secret_names_no_application(self) -> None:
        registry = ServiceTokenRegistry.parse(f"analytics:{SECRET}")

        presented = [SECRET, OTHER_SECRET]

        assert [registry.application_for(s) for s in presented] == ["analytics", None]

    def test_each_application_keeps_its_own_secret(self) -> None:
        registry = ServiceTokenRegistry.parse(
            f"analytics:{SECRET}, gene-page:{OTHER_SECRET}",
        )

        assert registry.application_for(SECRET) == "analytics"
        assert registry.application_for(OTHER_SECRET) == "gene-page"

    def test_padding_around_an_entry_is_not_part_of_the_secret(self) -> None:
        registry = ServiceTokenRegistry.parse(f"  analytics :  {SECRET}  ")

        assert registry.application_for(SECRET) == "analytics"

    def test_a_trailing_separator_is_ignored(self) -> None:
        registry = ServiceTokenRegistry.parse(f"analytics:{SECRET},")

        assert len(registry.tokens) == 1

    def test_an_entry_without_a_separator_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="application_id:secret"):
            ServiceTokenRegistry.parse(SECRET)

    def test_a_short_secret_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ServiceTokenRegistry.parse("analytics:too-short")

    def test_a_blank_application_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ServiceTokenRegistry.parse(f":{SECRET}")

    def test_a_repeated_application_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="analytics"):
            ServiceTokenRegistry.parse(f"analytics:{SECRET},analytics:{OTHER_SECRET}")

    def test_a_non_ascii_secret_matches_nothing_instead_of_raising(self) -> None:
        """Starlette decodes a header as latin-1, so any byte can reach the match."""
        registry = ServiceTokenRegistry.parse(f"analytics:{SECRET}")

        assert registry.application_for("caf\xe9-token-0123456789abcdefghij") is None
        assert registry.application_for("\U0001f512" * 40) is None
        assert registry.application_for(SECRET) == "analytics"

    def test_the_secret_stays_out_of_the_repr(self) -> None:
        registry = ServiceTokenRegistry.parse(f"analytics:{SECRET}")

        assert SECRET not in repr(registry)
        assert "analytics" in repr(registry)
