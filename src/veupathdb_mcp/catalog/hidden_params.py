from __future__ import annotations

from veupathdb.errors import ValidationError, param_message_rows


class HiddenParameterError(ValidationError):
    def __init__(
        self, name: str, search_name: str | None = None, *, unset: bool = False
    ) -> None:
        self.name = name
        where = f" of {search_name}" if search_name else ""
        fault = (
            f"{name} is a hidden parameter{where} with no value the site sets, so "
            "the search cannot run from the values given."
            if unset
            else f"{name} is a hidden parameter{where}: the site sets it, so it "
            "takes no value from you."
        )
        super().__init__(
            title="A hidden parameter takes no value",
            detail=fault,
            errors=param_message_rows({name: [fault]}),
        )
