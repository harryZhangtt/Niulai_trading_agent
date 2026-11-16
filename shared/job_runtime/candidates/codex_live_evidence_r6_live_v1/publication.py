"""Strict two-object publication with rollback receipt and recovery."""
from __future__ import annotations
import os,shutil
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from .contracts import ContractError,atomic_bytes,canonical_bytes,scan_forbidden,sha256_bytes
PUBLIC_FIELDS=frozenset(("schema_version","execution_id","operation_id","terminal_outcome","reason_code","selected_model","grant_seal_sha256","source_closure_sha256","expected_account_fingerprint_sha256","credential_reference_sha256","hard_usd_cap","final_cost_bounded_by_cap","not_before","deadline","catalog_membership","catalog_raw_sha256","catalog_raw_bytes","prompt_sha256","prompt_bytes","request_sha256","request_bytes","stdout_sha256","stdout_bytes","stderr_sha256","stderr_bytes","parser_sha256","sanitized_output_sha256","sanitized_output_bytes","admission_count","upstream_attempt_count","retry","replay","provider_status_calls","cleanup_complete","countable_observation","publication_atomic"))
class PublicationError(ContractError):
    def __init__(self,code:str,receipt:Mapping[str,Any])->None:super().__init__(code);self.receipt=dict(receipt)
def validate_projection(value:Mapping[str,Any])->None:
    if type(value) is not dict or set(value)!=PUBLIC_FIELDS:raise ContractError("R6_PUBLIC_ALLOWLIST_INVALID")
    if value["countable_observation"] is not False or value["publication_atomic"] is not True:raise ContractError("R6_PUBLIC_CONSTANT_INVALID")
    scan_forbidden(value,public=True)
def _fsync_tree(root:Path)->None:
    for p in root.rglob("*"):
        if p.is_file():
            fd=os.open(str(p),os.O_RDONLY);os.fsync(fd);os.close(fd)
    fd=os.open(str(root),os.O_RDONLY|getattr(os,"O_DIRECTORY",0));os.fsync(fd);os.close(fd)
def publish(private_final:Path,public_final:Path,evidence:Mapping[str,Any],projection:Mapping[str,Any],fail_after_private:bool=False)->Dict[str,Any]:
    scan_forbidden(evidence);validate_projection(projection)
    if private_final.exists() or public_final.exists():raise ContractError("R6_PUBLICATION_OVERWRITE")
    tx=sha256_bytes(canonical_bytes({"private":str(private_final),"public":str(public_final),"projection":dict(projection)}))[:16];ps=private_final.with_name("."+private_final.name+".staging-"+tx);ss=public_final.with_name("."+public_final.name+".staging-"+tx);receipt_path=private_final.parent/("publication-receipt-"+tx+".json")
    receipt={"transaction_id":tx,"private_committed":False,"public_committed":False,"rolled_back":False,"recovery_complete":False,"partial_publication":False,"two_object_atomic_protocol":True}
    try:
        for p in (ps,ss):p.mkdir(mode=0o700,parents=True)
        private_data=canonical_bytes(dict(evidence));public_data=canonical_bytes(dict(projection));(ps/"live-evidence.json").write_bytes(private_data);(ss/"live-evidence.json").write_bytes(public_data);_fsync_tree(ps);_fsync_tree(ss)
        os.replace(str(ps),str(private_final));receipt["private_committed"]=True
        if fail_after_private:raise OSError("synthetic partial publication")
        os.replace(str(ss),str(public_final));receipt["public_committed"]=True;receipt["recovery_complete"]=True;atomic_bytes(receipt_path,canonical_bytes(receipt));return dict(receipt,private_sha256=sha256_bytes(private_data),sanitized_sha256=sha256_bytes(public_data),receipt_path=str(receipt_path))
    except Exception as e:
        receipt["partial_publication"]=receipt["private_committed"]!=receipt["public_committed"]
        for p in (ps,ss,private_final,public_final):
            if p.exists():shutil.rmtree(str(p))
        receipt["rolled_back"]=True;receipt["recovery_complete"]=True;atomic_bytes(receipt_path,canonical_bytes(receipt));raise PublicationError("R6_PUBLICATION_RECOVERED",dict(receipt,receipt_path=str(receipt_path))) from e
