"""A computed field that pydantic serializes and a type checker reads as its value."""

from collections.abc import Callable
from typing import Protocol

from pydantic import computed_field


class Computed[T](Protocol):
    """A class attribute a type checker reads as the value it computes."""

    def __get__(self, instance: object, owner: type | None = None, /) -> T: ...


def computed[S, T](func: Callable[[S], T]) -> Computed[T]:
    """Serialize the value of a method like a field, typed as that value.

    mypy refuses a decorator stacked on ``@property``, so this wraps the
    property itself.
    """
    return computed_field(property(func))
