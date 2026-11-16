import hashlib,json,os,stat
from datetime import datetime,timezone
from pathlib import Path
REQUEST=b'{"synthetic":"request"}'
NOW=datetime(2030,1,1,tzinfo=timezone.utc)
def sha(data):return hashlib.sha256(data).hexdigest()
def fixture(name):
 p=Path(__file__).resolve().parents[2]/"fixtures"/"codex_live_evidence_r6_v1"/name;return json.loads(p.read_text())
def make(root):
 root=Path(root).resolve();os.chmod(root,0o700);exe=root/"executable";catalog=root/"model_catalog"
 contents={"executable":b"synthetic executable asset\n","model_catalog":b"model-other\nmodel-test\n","prompt":b"synthetic prompt\n"}
 for name,data in contents.items():p=root/name;p.write_bytes(data);os.chmod(p,0o500 if name=="executable" else 0o400)
 contents["canonical_argv"]=json.dumps([str(exe),"--model","model-test"],separators=(",",":")).encode()
 contents["canonical_config"]=b'{"request_retries":0,"stream_retries":0}'
 for name in ("canonical_argv","canonical_config"):
  p=root/name;p.write_bytes(contents[name]);os.chmod(p,0o400)
 translator=Path(__file__).resolve().parents[3]/"candidates/codex_live_evidence_r6_v1/translator.py";artifacts={}
 for name,data in contents.items():
  p=root/name;st=p.stat();v={"path":str(p),"bytes":len(data),"sha256":sha(data),"inode":st.st_ino,"owner":st.st_uid,"mode":stat.S_IMODE(st.st_mode)}
  if name=="executable":v["official_asset_ref"]="synthetic://official/test"
  if name=="model_catalog":v.update(parser_source_sha256=sha(translator.read_bytes()),selected_model_token="model-test",selected_model_occurrences=1)
  artifacts[name]=v
 identity={"execution_id":"r6-execution-new","job_id":"r6-job-new","slot_id":"r6-slot-new","attempt_id":"r6-attempt-new","operation_id":"r6-operation-new","provider_process_start_identity":"r6-process-new","gateway_id":"r6-gateway-new","request_id":"r6-request-new","request_fingerprint":sha(REQUEST)}
 prompt={"identity":dict(identity),"prompt_path":artifacts["prompt"]["path"],"bytes":artifacts["prompt"]["bytes"],"sha256":artifacts["prompt"]["sha256"],"job_id":identity["job_id"],"slot_id":identity["slot_id"],"attempt_id":identity["attempt_id"],"operation_id":identity["operation_id"],"provider_process_start_identity":identity["provider_process_start_identity"],"gateway_id":identity["gateway_id"],"treatment_fingerprint":"b"*64}
 budget={"catalog_preflight_count":1,"concurrency":1,"gateway_admission_max":1,"gateway_retries":0,"inference_invocation_max":1,"max_attempts":1,"max_workers":1,"request_retries":0,"stream_retries":0,"upstream_attempt_max":1,"second_admission_rejected":True}
 return {"schema_version":"r6-grant-v1","identity":identity,"enabled":False,"live_authority":False,"synthetic_only":True,"call_budget":budget,"artifacts":artifacts,"account":{"opaque_account_fingerprint":"c"*64,"expected_account_fingerprint":"c"*64,"entitlement":True,"model_access":True,"auth_checked_at":"2029-12-31T23:00:00Z","auth_expires_at":"2030-01-01T01:00:00Z","credential_reference_only":True},"budget":{"currency":"USD","hard_maximum":1,"cost_authority":"synthetic_non_authorizing","final_cost_receipt":None},"window":{"not_before":"2029-12-31T23:00:00Z","deadline":"2030-01-01T01:00:00Z"},"private_root":{"canonical_path":str(root),"owner_uid":os.getuid(),"mode_0700":True,"nofollow_components":True,"atomic_finalization":True},"prompt_process":prompt}
