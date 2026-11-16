"""Pure gates and exact canonical Engine post-write readback."""
from __future__ import annotations
import sqlite3
from typing import Any,Mapping
from .contracts import LIMITS,MODEL,canonical_bytes,sha256_bytes,validate_engine_readback,validate_held_manifest,require
def early(manifest:Mapping[str,Any],*,grant_reviewed:bool,account_binding:bool,cost_cap:float,combined_cap:float,window_minutes:int)->None:
    validate_held_manifest(manifest);require(grant_reviewed,"TRUSTED_GRANT_REVIEW_MISSING");require(account_binding,"ACCOUNT_BINDING_DRIFT");require(cost_cap==.01 and combined_cap==.02,"COST_CAP_DRIFT");require(window_minutes==30,"WINDOW_DRIFT");require(manifest["model"]==MODEL and manifest["model_membership"]is True,"MODEL_MEMBERSHIP_DRIFT")
def engine_readback(prepared,request,manifest):
    db=sqlite3.connect(prepared.engine_state/"schedule.sqlite",timeout=5);db.row_factory=sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE");job=request["logical_job_id"]
        counts={"job":db.execute("select count(*) from jobs where job_id=?",(job,)).fetchone()[0],"slot":db.execute("select count(*) from slots where job_id=?",(job,)).fetchone()[0],"attempt":db.execute("select count(*) from attempts a join slots s on s.slot_id=a.slot_id where s.job_id=?",(job,)).fetchone()[0],"prompt_artifact":db.execute("select count(*) from prompt_artifacts where sha256=?",(request["prompt_sha256"],)).fetchone()[0]}
        row=db.execute("select s.slot_id,a.attempt_id,a.artifact_ref,a.sha256,a.length,a.source_identity_sha256,a.binding_sha256 from slots s join attempts a on a.slot_id=s.slot_id where s.job_id=?",(job,)).fetchone();require(row is not None and row["slot_id"] and row["attempt_id"]==request["attempt_id"] and row["sha256"]==request["prompt_sha256"] and row["binding_sha256"]==request["prompt_binding_sha256"],"ENGINE_POST_WRITE_READBACK_DRIFT")
        op=request["operation_id"];pp="provider-process/"+sha256_bytes(canonical_bytes({"operation_id":op,"kind":"provider_process"}));rid="request/"+sha256_bytes(canonical_bytes({"operation_id":op,"kind":"request"}))
        x={"version":1,"verified":True,"job_id":job,"slot_id":row["slot_id"],"attempt_id":row["attempt_id"],"operation_id":op,"provider_process_id":pp,"request_id":rid,"native_prompt":{"artifact_ref":row["artifact_ref"],"sha256":row["sha256"],"bytes":row["length"],"source_identity_sha256":row["source_identity_sha256"],"binding_sha256":row["binding_sha256"]},"counts":counts,"transaction":"BEGIN_IMMEDIATE_POST_WRITE_READBACK"};x["digest"]=sha256_bytes(canonical_bytes(x));validate_engine_readback(x);require(manifest["prompt"]["sha256"]==x["native_prompt"]["sha256"] and manifest["prompt"]["bytes"]==x["native_prompt"]["bytes"],"NATIVE_PROMPT_MANIFEST_DRIFT");db.commit();return x
    except BaseException:db.rollback();raise
    finally:db.close()
