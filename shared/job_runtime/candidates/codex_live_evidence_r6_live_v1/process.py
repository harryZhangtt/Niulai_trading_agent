"""Injected fake-process boundary; no subprocess implementation exists."""
from typing import Any,Dict,Mapping,Optional
from .contracts import ContractError
class DenyProcess:
    def start(self,*args:Any,**kwargs:Any)->Dict[str,Any]:raise ContractError("R6_LIVE_PROCESS_DENIED")
class FakeProcess:
    def __init__(self,terminal:str="PASS",cleanup_failure:bool=False,raise_at:Optional[str]=None,identity_overrides:Optional[Mapping[str,str]]=None)->None:self.terminal=terminal;self.cleanup_failure=cleanup_failure;self.raise_at=raise_at;self.identity_overrides=dict(identity_overrides or {});self.starts=0;self.invocations=0;self.cleanup_calls=0
    def start(self,identity:Mapping[str,Any])->Dict[str,Any]:
        self.starts+=1
        if self.raise_at=="start":raise RuntimeError("synthetic process start failure")
        value={"provider_process_start_identity":identity["provider_process_start_identity"],"engine_identity":identity["engine_identity"],"operation_id":identity["operation_id"],"held":True};value.update(self.identity_overrides);return value
    def invoke(self,request:bytes)->Dict[str,Any]:
        self.invocations+=1
        if self.raise_at=="invoke":raise RuntimeError("synthetic invoke failure")
        return {"terminal":self.terminal,"stdout":b"synthetic output","stderr":b"","request_bytes":len(request)}
    def cleanup(self)->Dict[str,Any]:
        self.cleanup_calls+=1
        if self.raise_at=="cleanup":raise RuntimeError("synthetic cleanup exception")
        return {"complete":not self.cleanup_failure,"residual_children":1 if self.cleanup_failure else 0}
