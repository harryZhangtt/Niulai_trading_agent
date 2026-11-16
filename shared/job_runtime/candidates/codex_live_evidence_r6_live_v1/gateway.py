"""Request-local fake gateway backed by the single durable admission authority."""
from typing import Any,Dict,Mapping,Optional
from .contracts import ContractError,DuplicateAdmissionCriticalStop,DurableAuthorityStore,sha256_bytes
class DenyGateway:
    def admit(self,*args:Any,**kwargs:Any)->Dict[str,Any]:raise ContractError("R6_LIVE_GATEWAY_DENIED")
class FakeGateway:
    def __init__(self,store:DurableAuthorityStore,raise_after_persist:bool=False,identity_overrides:Optional[Mapping[str,str]]=None)->None:self.store=store;self.raise_after_persist=raise_after_persist;self.identity_overrides=dict(identity_overrides or {});self.admission_count=0;self.upstream_attempt_count=0
    def admit(self,request:bytes,identity:Mapping[str,Any],operation_key:str,process_receipt:Mapping[str,Any])->Dict[str,Any]:
        if operation_key!=self.store.operation_key(identity) or sha256_bytes(request)!=identity["request_fingerprint"]:raise ContractError("R6_REQUEST_IDENTITY_MISMATCH")
        receipt={"admission_count":1,"upstream_attempt_count":1,"request_fingerprint":identity["request_fingerprint"],"request_local_gateway_id":identity["request_local_gateway_id"],"request_local_gateway_fingerprint":identity["request_local_gateway_fingerprint"],"engine_identity":identity["engine_identity"],"provider_process_start_identity":process_receipt["provider_process_start_identity"],"operation_id":identity["operation_id"],"second_admission_rejected":True};receipt.update(self.identity_overrides)
        try:self.store.admit(operation_key,receipt)
        except DuplicateAdmissionCriticalStop as e:raise DuplicateAdmissionCriticalStop("R6_SECOND_ADMISSION_CRITICAL_STOP") from e
        self.admission_count=1;self.upstream_attempt_count=1
        if self.raise_after_persist:raise RuntimeError("synthetic post-admission gateway failure")
        return receipt
