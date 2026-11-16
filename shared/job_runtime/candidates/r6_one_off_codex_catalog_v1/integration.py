"""Separate narrow issuance boundary; real authentication acquisition is out of scope."""
from __future__ import annotations
from typing import Any,Callable,Tuple

def _make_boundary()->Tuple[Callable[[bytearray],object],Callable[[object],bytearray]]:
    issuer=object()
    class TransientAuthToken:
        __slots__=("_material","_issuer","_consumed")
        def __init__(self,material:bytearray,capability:object)->None:
            if capability is not issuer or type(material) is not bytearray or not material:raise TypeError("transient token construction rejected")
            self._material=material;self._issuer=capability;self._consumed=False
        @property
        def wiped(self)->bool:return all(value==0 for value in self._material)
    def issue(material:bytearray)->object:
        if type(material) is not bytearray or not material or b"\x00" in material:raise ValueError("invalid transient authentication material")
        return TransientAuthToken(material,issuer)
    def consume(token:object)->bytearray:
        if type(token) is not TransientAuthToken or token._issuer is not issuer or token._consumed:raise TypeError("transient token capability rejected")
        token._consumed=True;return token._material
    return issue,consume

issue_transient_auth_token,_consume_transient_token=_make_boundary()
del _make_boundary
__all__=["issue_transient_auth_token"]
