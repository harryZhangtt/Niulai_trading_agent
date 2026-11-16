"""Injected effect-none transport with deny-by-default effect capabilities."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
_EFFECTS=("provider","network","process","host","email","business")
@dataclass
class DenyEffectRecorder:
    _counts: dict = field(default_factory=lambda:{key:0 for key in _EFFECTS})
    def deny(self,effect: str) -> None:
        if effect not in self._counts: raise ValueError("PFL_EFFECT_KIND_INVALID")
        self._counts[effect]+=1;raise RuntimeError("PFL_EFFECT_DENIED")
    def snapshot(self) -> Mapping[str,int]: return MappingProxyType(dict(self._counts))
class EffectCapabilities:
    __slots__=("_recorder",)
    def __init__(self,recorder):object.__setattr__(self,"_recorder",recorder)
    def provider(self):self._recorder.deny("provider")
    def network(self):self._recorder.deny("network")
    def process(self):self._recorder.deny("process")
    def host(self):self._recorder.deny("host")
    def email(self):self._recorder.deny("email")
    def business(self):self._recorder.deny("business")
@dataclass
class FakeTransport:
    scenario: str
    recorder: DenyEffectRecorder
    dispatch_count: int=0
    def __post_init__(self):self.effects=EffectCapabilities(self.recorder)
    def mark_dispatch(self):self.dispatch_count+=1
