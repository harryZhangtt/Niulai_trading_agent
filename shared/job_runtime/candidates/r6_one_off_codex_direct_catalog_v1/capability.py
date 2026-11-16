"""Explicit-lifetime opaque transient bearer capability boundary."""
from __future__ import annotations
from contextlib import contextmanager
from typing import Callable, ContextManager, Dict, Iterator, Tuple


def _boundary() -> Tuple[Callable[[bytearray], ContextManager[object]], Callable[[object], bytearray], Callable[[object], bool], Callable[[], int]]:
    vault: Dict[object, bytearray] = {}

    class TransientBearer:
        __slots__ = ()
        def __repr__(self) -> str:
            return "<TransientBearer opaque>"

    def wipe(material: bytearray) -> None:
        for index in range(len(material)):
            material[index] = 0
        material.clear()

    def issue(source: bytearray) -> object:
        if type(source) is not bytearray:
            raise ValueError("transient bearer source rejected")
        material = None
        try:
            safe = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~+/"
            if not source or any(value not in safe + b"=" for value in source):
                raise ValueError("transient bearer source rejected")
            first_padding = source.find(b"=")
            if first_padding >= 0 and any(value != ord("=") for value in source[first_padding:]):
                raise ValueError("transient bearer source rejected")
            material = bytearray(source)
        finally:
            wipe(source)
        capability = TransientBearer()
        vault[capability] = material
        return capability

    def revoke(capability: object) -> bool:
        if type(capability) is not TransientBearer:
            return False
        material = vault.pop(capability, None)
        if material is None:
            return False
        wipe(material)
        return True

    @contextmanager
    def scope(source: bytearray) -> Iterator[object]:
        capability = issue(source)
        try:
            yield capability
        finally:
            revoke(capability)

    def consume(capability: object) -> bytearray:
        if type(capability) is not TransientBearer or capability not in vault:
            raise TypeError("transient bearer capability rejected")
        return vault.pop(capability)

    def active_count() -> int:
        return len(vault)

    return scope, consume, revoke, active_count


transient_bearer_scope, _consume_transient_bearer, _revoke_transient_bearer, _active_material_count = _boundary()
del _boundary
__all__ = ["transient_bearer_scope"]
