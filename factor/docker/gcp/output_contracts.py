"""Outcome-free structural/aggregate/catalog output contracts for GCP jobs."""
import hashlib,json,re
SHA=re.compile(r"[a-f0-9]{64}\Z"); ID=re.compile(r"[a-z][a-z0-9-]{2,95}\Z")
class OutputError(ValueError):pass
def req(x,c):
    if not x:raise OutputError(c)
def canonical(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def strict(v,k,c):req(type(v)is dict and set(v)==set(k),c);return v
def sha(x):req(type(x)is str and SHA.fullmatch(x),"GCP_OUTPUT_SHA")
def ident(x):req(type(x)is str and ID.fullmatch(x),"GCP_OUTPUT_ID")
def object_binding(v):
    strict(v,{"bucket","object","generation","metageneration","commitment_sha256"},"GCP_OBJECT_SCHEMA");ident(v["bucket"]);req(type(v["object"])is str and 1<=len(v["object"])<=256 and not v["object"].startswith("/")and".."not in v["object"].split("/"),"GCP_OBJECT_PATH");req(type(v["generation"])is str and v["generation"].isdigit()and int(v["generation"])>0 and type(v["metageneration"])is int and v["metageneration"]>0,"GCP_OBJECT_VERSION");sha(v["commitment_sha256"]);return v
def validate_structural(v):
    strict(v,{"schema_version","kind","role","job_name","execution_id","image_digest_sha256","request_sha256","artifact_binding","outcome_accessed","protected_labels_accessed","performance_claim","raw_rows_emitted"},"GCP_STRUCTURAL_SCHEMA");req(v["schema_version"]==1 and v["kind"]=="factor_structural_receipt"and v["role"]in{"controller","executor"}and v["outcome_accessed"]is False and v["protected_labels_accessed"]is False and v["performance_claim"]=="withheld"and v["raw_rows_emitted"]is False,"GCP_STRUCTURAL_INVALID");ident(v["job_name"]);ident(v["execution_id"]);sha(v["image_digest_sha256"]);sha(v["request_sha256"]);object_binding(v["artifact_binding"]);return v
def validate_aggregate(v):
    strict(v,{"schema_version","kind","role","job_name","execution_id","image_digest_sha256","checkpoint_binding","label_binding","aggregate_commitment_sha256","output_schema_id","redaction_policy_id","raw_rows_emitted","labels_emitted","structured_stdout_only","performance_claim"},"GCP_AGGREGATE_SCHEMA");req(v["schema_version"]==1 and v["kind"]=="factor_aggregate_receipt"and v["role"]in{"evaluator","checker"}and v["output_schema_id"]==f"factor-{v['role']}-aggregate-v1"and v["redaction_policy_id"]=="factor-no-sensitive-output-v1"and v["raw_rows_emitted"]is False and v["labels_emitted"]is False and v["structured_stdout_only"]is True and v["performance_claim"]=="withheld","GCP_AGGREGATE_INVALID");ident(v["job_name"]);ident(v["execution_id"]);sha(v["image_digest_sha256"]);sha(v["aggregate_commitment_sha256"]);object_binding(v["checkpoint_binding"]);object_binding(v["label_binding"]);return v
def validate_catalog(v):
    strict(v,{"schema_version","kind","release_id","manifest_commitment_sha256","evaluator_receipt_sha256","checker_receipt_sha256","approval_commitments","signature_commitment_sha256","catalog_binding","publication_active"},"GCP_CATALOG_SCHEMA");req(v["schema_version"]==1 and v["kind"]=="factor_publication_catalog_entry"and v["publication_active"]is False and type(v["approval_commitments"])is list and len(v["approval_commitments"])==2 and len(set(v["approval_commitments"]))==2,"GCP_CATALOG_INVALID");ident(v["release_id"]);[sha(v[k])for k in("manifest_commitment_sha256","evaluator_receipt_sha256","checker_receipt_sha256","signature_commitment_sha256")];[sha(x)for x in v["approval_commitments"]];object_binding(v["catalog_binding"]);return v
