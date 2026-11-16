"""Durable ordered request-local Ferry admission observer; no transport."""
from __future__ import annotations
from pathlib import Path
from .contracts import ContractError,MODEL,canonical_bytes,sha256_bytes,validate_engine_readback,validate_ferry_receipt
from .publication import PublicationTrace,atomic_file_noreplace
class FakeFerryObserver:
    def __init__(self):self.receipt_value=None;self.status_calls=0
    @property
    def admission_count(self):return 0 if self.receipt_value is None else 1
    @property
    def upstream_count(self):return 0 if self.receipt_value is None else self.receipt_value["upstream_count"]
    @property
    def second_reject_count(self):return 0 if self.receipt_value is None else self.receipt_value["second_reject_count"]
    def admit(self,root,readback,spec,grant_digest,events,expected_readback):
        if self.receipt_value is not None:self.receipt_value["second_reject_count"]=1;raise ContractError("FERRY_SECOND_ADMISSION_REJECTED")
        validate_engine_readback(readback)
        if readback!=expected_readback or not events or events[-1]!={"sequence":1,"type":"ENGINE_READBACK_VERIFIED","digest":readback["digest"]}:raise ContractError("FERRY_ENGINE_ORDER_OR_BINDING_DRIFT")
        req={"job_id":readback["job_id"],"slot_id":readback["slot_id"],"attempt_id":readback["attempt_id"],"operation_id":readback["operation_id"],"provider_process_id":readback["provider_process_id"],"request_id":readback["request_id"],"model":MODEL,"native_prompt_artifact_identity":readback["native_prompt"]["source_identity_sha256"],"native_prompt_sha256":readback["native_prompt"]["sha256"],"grant_digest":grant_digest,"launch_spec_digest":spec["digest"]};fp=sha256_bytes(canonical_bytes(req));obs="observer/"+sha256_bytes(canonical_bytes({"request":fp,"kind":"ferry"}))
        events.append({"sequence":2,"type":"FERRY_ADMISSION_DURABLE","engine_readback_digest":readback["digest"]})
        x={"version":1,"observer_id":obs,**req,"request_fingerprint":fp,"engine_readback_event":1,"admission_event":2,"admission_count":1,"upstream_count":0,"second_reject_count":0,"status_calls":0,"durable":True};validate_ferry_receipt(x);root.mkdir(mode=0o700,parents=True,exist_ok=True);atomic_file_noreplace(root/"admission.json",canonical_bytes(x),PublicationTrace(),"ferry");self.receipt_value=x;return fp
    def observe_upstream(self):
        if self.receipt_value is None or self.receipt_value["upstream_count"]:raise ContractError("FERRY_UPSTREAM_MULTIPLICITY")
        self.receipt_value["upstream_count"]=1;return self.receipt()
    def receipt(self):
        if self.receipt_value is None:return None
        x=dict(self.receipt_value);validate_ferry_receipt(x);return x
