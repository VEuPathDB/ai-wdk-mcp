"""What a caller sees when the semantic index cannot answer."""


class SemanticIndexUnavailableError(RuntimeError):
    """The index cannot be read or written now, so the caller ranks without it."""
