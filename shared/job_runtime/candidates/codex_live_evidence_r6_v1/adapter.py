"""Injected provider boundary. Live capabilities are absent and deny by default."""
from __future__ import annotations
from typing import Any, Dict, Mapping
from .contracts import R6ContractError, validate_identity

_SCENARIOS=("nominal","post_admission_ambiguity","malformed_terminal","missing_terminal")
def validate_synthetic_observation(scenario:Any,observation:Any)->None:
    """Shared adapter/translator boundary validation without provider effects."""
    if scenario not in _SCENARIOS or type(observation) is not dict:
        raise R6ContractError("R6_SYNTHETIC_ADAPTER_INVALID")
    if "terminal_status" in observation and type(observation["terminal_status"]) is not str:
        raise R6ContractError("R6_MALFORMED_TERMINAL")
class DenyByDefaultLiveBoundary:
    def __getattr__(self,_name:str)->Any:raise R6ContractError("R6_LIVE_BOUNDARY_DENIED")
class SyntheticObservationAdapter:
    def __init__(self,scenario:str,observation:Mapping[str,Any])->None:
        validate_synthetic_observation(scenario,observation)
        self.scenario=scenario;self._observation=dict(observation);self.observation_count=0
    def observe_admitted_synthetic(self,identity:Mapping[str,Any])->Dict[str,Any]:
        if self.observation_count:raise R6ContractError("R6_SYNTHETIC_OBSERVATION_DUPLICATE")
        self.observation_count=1
        return {"identity":dict(validate_identity(dict(identity))),"scenario":self.scenario,"observation":dict(self._observation),"synthetic":True}
