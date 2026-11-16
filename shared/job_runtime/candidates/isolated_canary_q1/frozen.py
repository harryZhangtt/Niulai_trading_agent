"""Deeply immutable JSON-compatible containers."""
from __future__ import annotations

from typing import Any, Mapping


class FrozenDict(dict):
    def _deny(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("CANARY_IMMUTABLE")
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _deny


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenDict((key, freeze(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value
