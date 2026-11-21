from __future__ import annotations

from veupathdb.errors import ValidationError, param_message_rows


class SiteSetParameterError(ValidationError):
    def __init__(
        self, name: str, search_name: str | None = None, *, unset: bool = False
    ) -> None:
        self.name = name
        where = f"{name} on {search_name}" if search_name else name
        fault = (
            f"{where} is set by the site, and the site gives it no value, so the "
            "search cannot run from the values given."
            if unset
            else f"{where} is set by the site: the website does not offer it, and it "
            "is sent at the value the site gives it under the other values. Leave it out."
        )
        super().__init__(
            title="A site-set parameter takes no value",
            detail=fault,
            errors=param_message_rows({name: [fault]}),
        )
