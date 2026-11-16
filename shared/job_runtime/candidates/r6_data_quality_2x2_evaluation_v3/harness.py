"""Owner-rooted, provider-free human-grade intake and evidence derivation v3."""
from __future__ import annotations
import hashlib, json, os, re, stat
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

class ContractError(ValueError): pass
def require(v: bool, code: str) -> None:
    if not v: raise ContractError(code)
def canonical_bytes(v: Any) -> bytes:
    try:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
    except (TypeError,ValueError,UnicodeError,RecursionError):raise ContractError("CANONICAL_VALUE_INVALID") from None
def sha256_json(v: Any) -> str:return hashlib.sha256(canonical_bytes(v)).hexdigest()
SHA=re.compile(r"[0-9a-f]{64}\Z")
CELL_ORDER=("R6DQ-7F2C91A4","R6DQ-1B8E43D7","R6DQ-C4A7095E","R6DQ-92D6F0B3")
CELL_MAP={"R6DQ-7F2C91A4":("CLAUDE","OFF"),"R6DQ-1B8E43D7":("CODEX","ON"),"R6DQ-C4A7095E":("CLAUDE","ON"),"R6DQ-92D6F0B3":("CODEX","OFF")}
ALIASES=dict(zip(CELL_ORDER,("BLIND-01","BLIND-02","BLIND-03","BLIND-04")))
DIMENSIONS=("freshness","richness","depth","accuracy","citation_accuracy","source_coverage","incremental_information_value","cost","latency")
LEVELS=("L0_UNUSABLE","L1_WEAK","L2_ADEQUATE","L3_STRONG","L4_EXCEPTIONAL")
HARD_GATES=("cell_identity_unique","frozen_payload_cutoff","provider_model_effort","common_tool_web_allowance","common_budget_time","common_engine_contracts","one_attempt_no_replay","raw_and_sanitized_custody","reference_parseability","terminal_unknown_durability","dq_treatment_integrity","all_variants_retained")
REF_KINDS=("sanitized_output","evidence_record","source_inventory","citation_inventory","deterministic_gate_report","raw_custody_receipt")
LEAK_TOKENS=frozenset(("provider","model","addon","dq","layer","order","cost","latency","claude","codex","opus","gpt","on","off","baseline","treatment","sol"))
AUTH_KINDS=("grader_registry","grader_registry_review","grader_grant","grader_grant_review","blind_map_commitment")
ALL_ARTIFACT_KINDS=REF_KINDS+AUTH_KINDS
TRUSTED_LIVE_REGISTRY_REVIEW_SHA256S=frozenset()
SCHEMA_DIR=Path(__file__).resolve().parent

def closed(v: Mapping[str,Any], required: Iterable[str], code: str) -> None:
    require(isinstance(v,Mapping),code+"_TYPE");r=tuple(required);require(set(v)==set(r),code+"_FIELDS")
def seal(body: Mapping[str,Any])->Dict[str,Any]:
    b=dict(body);out=dict(b);out["artifact_sha256"]=sha256_json(b);out["artifact_bytes"]=len(canonical_bytes(b));return out
def verify_seal(v: Mapping[str,Any],code:str)->None:
    body={k:x for k,x in v.items() if k not in ("artifact_sha256","artifact_bytes")}
    require(v.get("immutable") is True,code+"_IMMUTABLE");require(v.get("artifact_sha256")==sha256_json(body),code+"_HASH");require(v.get("artifact_bytes")==len(canonical_bytes(body)),code+"_BYTES")

class ArtifactStore:
    """Read-only owner-controlled JSON artifact root with no-follow reads."""
    def __init__(self, root: Path):
        self.root=Path(root)
        require(self.root.is_absolute(),"ROOT_NOT_ABSOLUTE")
        st=os.lstat(str(self.root));require(stat.S_ISDIR(st.st_mode),"ROOT_NOT_DIRECTORY");require(not stat.S_ISLNK(st.st_mode),"ROOT_SYMLINK")
        require(st.st_uid==os.getuid(),"ROOT_OWNER");require(stat.S_IMODE(st.st_mode)==0o700,"ROOT_MODE")
    def root_id(self)->str:
        st=os.lstat(str(self.root));require(stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode),"ROOT_CHANGED");require(st.st_uid==os.getuid() and stat.S_IMODE(st.st_mode)==0o700,"ROOT_CHANGED")
        return sha256_json({"device":st.st_dev,"inode":st.st_ino})
    def read(self, ref: Mapping[str,Any])->Any:
        closed(ref,("kind","path","sha256","bytes","canonical_content_sha256","immutable_at_ms"),"REF")
        require(ref["kind"] in ALL_ARTIFACT_KINDS,"REF_KIND");raw_path=ref["path"]
        require(isinstance(raw_path,str) and raw_path,"REF_PATH")
        require(not raw_path.startswith("/") and "\\" not in raw_path,"REF_TRAVERSAL")
        lexical_parts=raw_path.split("/");require(all(part not in ("",".","..") for part in lexical_parts),"REF_TRAVERSAL")
        tokens={token for part in lexical_parts for token in re.findall(r"[a-z0-9]+",part.lower())};require(not(tokens & LEAK_TOKENS),"REF_PATH_LEAKAGE")
        p=PurePosixPath(*lexical_parts);require(not p.is_absolute(),"REF_TRAVERSAL")
        self.root_id()
        nofollow=getattr(os,"O_NOFOLLOW",0);directory=getattr(os,"O_DIRECTORY",0)
        try:dirfd=os.open(str(self.root),os.O_RDONLY|directory|nofollow)
        except OSError as e:raise ContractError("REF_ROOT_OPEN_NOFOLLOW") from e
        opened=[dirfd]
        try:
            for part in p.parts[:-1]:
                nxt=os.open(part,os.O_RDONLY|directory|nofollow,dir_fd=dirfd);opened.append(nxt);dirfd=nxt
                dst=os.fstat(dirfd);require(stat.S_ISDIR(dst.st_mode) and dst.st_uid==os.getuid(),"REF_PARENT_OWNER");require(stat.S_IMODE(dst.st_mode)==0o700,"REF_PARENT_MODE")
            fd=os.open(p.parts[-1],os.O_RDONLY|nofollow,dir_fd=dirfd);opened.append(fd)
            st=os.fstat(fd);require(stat.S_ISREG(st.st_mode),"REF_NOT_REGULAR");require(st.st_uid==os.getuid(),"REF_OWNER");require(stat.S_IMODE(st.st_mode)==0o600,"REF_MODE")
            data=b""
            while True:
                chunk=os.read(fd,65536)
                if not chunk:break
                data+=chunk
        except OSError as e:raise ContractError("REF_OPEN_NOFOLLOW") from e
        finally:
            for x in reversed(opened):
                try:os.close(x)
                except OSError:pass
        require(isinstance(ref["bytes"],int) and ref["bytes"]==len(data),"REF_BYTES")
        require(bool(SHA.fullmatch(str(ref["sha256"]))) and hashlib.sha256(data).hexdigest()==ref["sha256"],"REF_HASH")
        try:value=json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError) as e:raise ContractError("REF_JSON") from e
        require(bool(SHA.fullmatch(str(ref["canonical_content_sha256"]))) and sha256_json(value)==ref["canonical_content_sha256"],"REF_CANONICAL_CONTENT")
        require(isinstance(ref["immutable_at_ms"],int) and ref["immutable_at_ms"]>0,"REF_TIME")
        return value

def preflight_readiness(storage: Mapping[str,Any])->Dict[str,Any]:
    names=("artifact-ref-v3.schema.json","blind-packet-v3.schema.json","evaluation-storage-v3.schema.json","grade-record-v3.schema.json","evidence-record-v3.schema.json","deterministic-gate-report-v3.schema.json","sanitized-output-v3.schema.json","source-inventory-v3.schema.json","citation-inventory-v3.schema.json","raw-custody-receipt-v3.schema.json","grader-registry-v3.schema.json","grader-review-v3.schema.json","grader-grant-v3.schema.json","blind-map-commitment-v3.schema.json")
    checked=[]
    for name in names:
        p=SCHEMA_DIR/name;require(p.is_file(),"PREFLIGHT_SCHEMA_MISSING");s=json.loads(p.read_text())
        require(s.get("$schema")=="https://json-schema.org/draft/2020-12/schema" and s.get("type")=="object" and s.get("additionalProperties") is False,"PREFLIGHT_SCHEMA_OPEN")
        require(set(s.get("required",()))<=set(s.get("properties",{})),"PREFLIGHT_SCHEMA_NESTED")
        checked.append({"path":name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size})
    closed(storage,("version","activation","provider_calls_permitted","root","atomic_create","no_replace","artifact_kinds"),"STORAGE")
    require(storage["version"]==3 and storage["activation"] is False and storage["provider_calls_permitted"] is False,"STORAGE_DISABLED")
    require(storage["atomic_create"] is True and storage["no_replace"] is True and set(storage["artifact_kinds"])>=set(ALL_ARTIFACT_KINDS)|{"blind_packet","grade","metric","unblind"},"STORAGE_POLICY")
    ArtifactStore(Path(storage["root"]))
    return {"status":"PASS_PROVIDER_FREE_PREFLIGHT_V3","provider_calls_permitted":False,"schemas":checked}

def validate_intake(kind:str,value:Mapping[str,Any],alias:str)->None:
    if kind=="evidence_record":validate_evidence(value,alias);return
    if kind=="deterministic_gate_report":
        closed(value,("version","blind_alias","hard_gates"),"GATE_REPORT");require(value["version"]==3 and value["blind_alias"]==alias and set(value["hard_gates"])==set(HARD_GATES) and all(x in ("PASS","FAIL") for x in value["hard_gates"].values()),"GATE_REPORT_VALUE");return
    if kind=="sanitized_output":closed(value,("version","blind_alias","text"),"SANITIZED_OUTPUT");require(isinstance(value["text"],str),"SANITIZED_OUTPUT_VALUE")
    elif kind=="source_inventory":
        closed(value,("version","blind_alias","sources"),"SOURCE_INVENTORY")
        require(isinstance(value["sources"],list),"SOURCE_LIST");
        for x in value["sources"]:closed(x,("id","url","cutoff_ok"),"SOURCE_ITEM");require(isinstance(x["id"],str) and bool(x["id"].strip()) and isinstance(x["url"],str) and bool(x["url"].strip()) and isinstance(x["cutoff_ok"],bool),"SOURCE_ITEM_VALUE")
    elif kind=="citation_inventory":
        closed(value,("version","blind_alias","citations"),"CITATION_INVENTORY")
        require(isinstance(value["citations"],list),"CITATION_LIST");
        for x in value["citations"]:closed(x,("id","source_id","claim_id"),"CITATION_ITEM");require(all(isinstance(x[k],str) and bool(x[k].strip()) for k in ("id","source_id","claim_id")),"CITATION_ITEM_VALUE")
    elif kind=="raw_custody_receipt":closed(value,("version","blind_alias","raw_sha256","owner_private"),"CUSTODY")
    else:raise ContractError("INTAKE_KIND")
    require(value["version"]==3 and value["blind_alias"]==alias,"INTAKE_ID")
    if kind=="raw_custody_receipt":require(value["owner_private"] is True and bool(SHA.fullmatch(str(value["raw_sha256"]))),"CUSTODY_VALUE")

def binding_signature(domain:str,subject_sha:str,reviewer_id:str,status:str="CLEAN")->str:
    return sha256_json({"domain":domain,"subject_content_sha256":subject_sha,"reviewer_id":reviewer_id,"status":status})

def validate_review(value:Mapping[str,Any],domain:str)->None:
    closed(value,("version","subject_content_sha256","reviewer_id","status","signature"),"AUTH_REVIEW")
    require(value["version"]==3 and isinstance(value["reviewer_id"],str) and bool(value["reviewer_id"].strip()) and value["status"]=="CLEAN" and bool(SHA.fullmatch(str(value["subject_content_sha256"]))),"AUTH_REVIEW_VALUE")
    require(value["signature"]==binding_signature(domain,value["subject_content_sha256"],value["reviewer_id"]),"AUTH_REVIEW_SIGNATURE")

def validate_registry(value:Mapping[str,Any])->None:
    closed(value,("version","registry_id","registry_kind","countable","graders"),"REGISTRY")
    require(value["version"]==3 and isinstance(value["registry_id"],str) and bool(value["registry_id"].strip()) and value["registry_kind"] in ("FIXTURE","LIVE") and isinstance(value["countable"],bool) and isinstance(value["graders"],list),"REGISTRY_VALUE")
    require((value["registry_kind"]=="FIXTURE")==(value["countable"] is False),"REGISTRY_RELABEL")
    seen=set()
    for g in value["graders"]:
        closed(g,("grader_id","role"),"REGISTRY_GRADER");require(isinstance(g["grader_id"],str) and bool(g["grader_id"].strip()) and g["role"] in ("G1","G2","G3") and g["grader_id"] not in seen,"REGISTRY_GRADER_VALUE");seen.add(g["grader_id"])
    require({g["role"] for g in value["graders"]}=={"G1","G2","G3"},"REGISTRY_ROLES")

def validate_grant(value:Mapping[str,Any])->None:
    closed(value,("version","registry_id","grader_id","role","blind","countable","valid_from_ms","valid_through_ms"),"GRANT")
    require(value["version"]==3 and all(isinstance(value[k],str) and bool(value[k].strip()) for k in ("registry_id","grader_id")) and value["role"] in ("G1","G2","G3") and value["blind"] is True and isinstance(value["countable"],bool),"GRANT_VALUE")
    require(isinstance(value["valid_from_ms"],int) and isinstance(value["valid_through_ms"],int) and value["valid_from_ms"]<value["valid_through_ms"],"GRANT_TIME")

def validate_map_commitment(value:Mapping[str,Any])->None:
    closed(value,("version","block_id","commitment_sha256","committed_at_ms","pre_call"),"MAP_COMMITMENT")
    require(value["version"]==3 and isinstance(value["block_id"],str) and bool(value["block_id"].strip()) and bool(SHA.fullmatch(str(value["commitment_sha256"]))) and isinstance(value["committed_at_ms"],int) and value["committed_at_ms"]>0 and value["pre_call"] is True,"MAP_COMMITMENT_VALUE")

class GraderAuthority:
    """Fixed registry and independently reviewed role grants, external to grades."""
    def __init__(self,store:ArtifactStore,registry_ref:Mapping[str,Any],registry_review_ref:Mapping[str,Any],grant_pairs:Mapping[str,Sequence[Mapping[str,Any]]],fixture:bool):
        self.store=store;self.fixture=fixture;self.registry_ref=dict(registry_ref);self.registry_review_ref=dict(registry_review_ref)
        require(registry_ref["kind"]=="grader_registry" and registry_review_ref["kind"]=="grader_registry_review","AUTH_REGISTRY_REF")
        registry=store.read(registry_ref);review=store.read(registry_review_ref);validate_registry(registry);validate_review(review,"R6DQ_GRADER_REGISTRY_REVIEW_V3")
        require(review["subject_content_sha256"]==registry_ref["canonical_content_sha256"],"AUTH_REGISTRY_REVIEW_BINDING")
        if fixture:require(registry["registry_kind"]=="FIXTURE" and registry["countable"] is False,"AUTH_FIXTURE_REGISTRY")
        else:
            require(registry["registry_kind"]=="LIVE" and registry["countable"] is True,"AUTH_LIVE_REGISTRY")
            require(registry_review_ref["sha256"] in TRUSTED_LIVE_REGISTRY_REVIEW_SHA256S,"LIVE_REGISTRY_NOT_EXTERNALLY_PINNED")
        self.registry=registry;self.grants={}
        require(set(grant_pairs)=={"G1","G2","G3"},"AUTH_GRANT_ROLES")
        roster={(x["role"],x["grader_id"]) for x in registry["graders"]}
        for role,pair in grant_pairs.items():
            require(isinstance(pair,Sequence) and len(pair)==2,"AUTH_GRANT_PAIR");grant_ref,review_ref=pair
            require(grant_ref["kind"]=="grader_grant" and review_ref["kind"]=="grader_grant_review","AUTH_GRANT_REF")
            grant=store.read(grant_ref);grant_review=store.read(review_ref);validate_grant(grant);validate_review(grant_review,"R6DQ_GRADER_GRANT_REVIEW_V3")
            require(grant_review["subject_content_sha256"]==grant_ref["canonical_content_sha256"],"AUTH_GRANT_REVIEW_BINDING")
            require(grant["registry_id"]==registry["registry_id"] and grant["role"]==role and (role,grant["grader_id"]) in roster,"AUTH_GRANT_ROSTER")
            require(grant["countable"]==registry["countable"],"AUTH_GRANT_COUNTABILITY")
            self.grants[role]={"grant":grant,"grant_ref":dict(grant_ref),"review_ref":dict(review_ref)}
    def authorize(self,role:str,human_reviewer_id:str,produced_at_ms:int,grant_digest:str)->None:
        x=self.grants[role];g=x["grant"]
        require(human_reviewer_id==g["grader_id"] and grant_digest==x["grant_ref"]["canonical_content_sha256"],"GRADE_EXTERNAL_GRANT_BINDING")
        require(g["valid_from_ms"]<=produced_at_ms<=g["valid_through_ms"],"GRADE_GRANT_TIME")

def validate_packet_runtime(store:ArtifactStore,p:Mapping[str,Any])->None:
    fields=("version","packet_id","blind_alias","artifact_root_id","refs","refs_sha256","blind_map_commitment_ref","blind_map_commitment_content_sha256","committed_at_ms","pre_call_at_ms","masking_breach","immutable","artifact_sha256","artifact_bytes")
    closed(p,fields,"PACKET");verify_seal(p,"PACKET");require(p["version"]==3 and isinstance(p["packet_id"],str) and bool(p["packet_id"].strip()) and p["blind_alias"] in ALIASES.values() and p["artifact_root_id"]==store.root_id(),"PACKET_ID")
    require(isinstance(p["refs"],list) and len(p["refs"])==6,"PACKET_REF_COUNT")
    require(tuple(x.get("kind") for x in p["refs"])==REF_KINDS and len({x["kind"] for x in p["refs"]})==6,"PACKET_REF_KINDS")
    require(p["refs_sha256"]==sha256_json(p["refs"]),"PACKET_REFS_DIGEST")
    for ref in p["refs"]:validate_intake(ref["kind"],store.read(ref),p["blind_alias"])
    cref=p["blind_map_commitment_ref"];require(cref["kind"]=="blind_map_commitment","PACKET_MAP_REF");cv=store.read(cref);validate_map_commitment(cv);require(p["blind_map_commitment_content_sha256"]==cref["canonical_content_sha256"],"PACKET_MAP_BINDING")
    require(cv["committed_at_ms"]<=p["pre_call_at_ms"]<=p["committed_at_ms"] and cref["immutable_at_ms"]<=p["pre_call_at_ms"],"PACKET_MAP_NOT_PRECALL")

def build_blind_packet(store:ArtifactStore,blind_alias:str,refs:Sequence[Mapping[str,Any]],map_commitment_ref:Mapping[str,Any],committed_at_ms:int,pre_call_at_ms:int,masking_breach:bool=False)->Dict[str,Any]:
    require(blind_alias in ALIASES.values(),"PACKET_ALIAS");require(isinstance(committed_at_ms,int) and isinstance(pre_call_at_ms,int),"PACKET_TIME")
    require(isinstance(refs,Sequence) and len(refs)==6,"PACKET_REF_COUNT");require(tuple(x.get("kind") for x in refs)==REF_KINDS,"PACKET_REF_KINDS")
    require(len({x["kind"] for x in refs})==6,"PACKET_REF_DUPLICATE")
    ordered=[]
    for ref in refs:
        value=store.read(ref);validate_intake(ref["kind"],value,blind_alias);require(ref["immutable_at_ms"]<=committed_at_ms,"PACKET_REF_AFTER_COMMIT");ordered.append(dict(ref))
    require(map_commitment_ref.get("kind")=="blind_map_commitment","PACKET_MAP_REF");cv=store.read(map_commitment_ref);validate_map_commitment(cv)
    require(cv["committed_at_ms"]<=pre_call_at_ms<=committed_at_ms and map_commitment_ref["immutable_at_ms"]<=pre_call_at_ms,"PACKET_MAP_NOT_PRECALL")
    body={"version":3,"packet_id":"packet/"+blind_alias,"blind_alias":blind_alias,"artifact_root_id":store.root_id(),"refs":ordered,"refs_sha256":sha256_json(ordered),"blind_map_commitment_ref":dict(map_commitment_ref),"blind_map_commitment_content_sha256":map_commitment_ref["canonical_content_sha256"],"committed_at_ms":committed_at_ms,"pre_call_at_ms":pre_call_at_ms,"masking_breach":bool(masking_breach),"immutable":True}
    out=seal(body);validate_packet_runtime(store,out);return out

def seal_grade(record: Mapping[str,Any])->Dict[str,Any]:
    require("artifact_sha256" not in record and "artifact_bytes" not in record,"GRADE_ALREADY_SEALED");b=dict(record);b["immutable"]=True;return seal(b)
def dimension_map(g:Mapping[str,Any])->Dict[str,str]:return {x["dimension"]:x["level"] for x in g["dimensions"]}
def gate_map(g:Mapping[str,Any])->Dict[str,str]:return {x["gate"]:x["disposition"] for x in g["hard_gates"]}
def validate_grade(g:Mapping[str,Any],p:Mapping[str,Any],authority:GraderAuthority)->None:
    fields=("version","grade_id","cell_blind_alias","packet_sha256","packet_refs_sha256","grader_role","human_reviewer_id","grader_grant_content_sha256","blind","dimensions","hard_gates","evidence_refs","comments","independence_attestation","packet_committed_at_ms","produced_at_ms","immutable","artifact_sha256","artifact_bytes")
    closed(g,fields,"GRADE");verify_seal(g,"GRADE");validate_packet_runtime(authority.store,p)
    require(g["version"]==3 and isinstance(g["grade_id"],str) and bool(g["grade_id"].strip()),"GRADE_ID");require(g["grader_role"] in ("G1","G2","G3") and isinstance(g["human_reviewer_id"],str) and bool(g["human_reviewer_id"].strip()),"GRADE_ROLE")
    require(g["cell_blind_alias"]==p["blind_alias"] and g["packet_sha256"]==p["artifact_sha256"] and g["packet_refs_sha256"]==p["refs_sha256"],"GRADE_PACKET_BINDING");require(g["packet_committed_at_ms"]==p["committed_at_ms"] and isinstance(g["produced_at_ms"],int) and g["produced_at_ms"]>p["committed_at_ms"],"GRADE_PREPACKET");require(g["blind"] is True,"GRADE_BLIND")
    authority.authorize(g["grader_role"],g["human_reviewer_id"],g["produced_at_ms"],g["grader_grant_content_sha256"])
    require(isinstance(g["dimensions"],list) and len(g["dimensions"])==len(DIMENSIONS),"GRADE_DIMENSIONS")
    for expected,x in zip(DIMENSIONS,g["dimensions"]):closed(x,("dimension","level"),"GRADE_DIMENSION");require(x["dimension"]==expected and x["level"] in LEVELS,"GRADE_DIMENSION_ORDER")
    require(isinstance(g["hard_gates"],list) and len(g["hard_gates"])==len(HARD_GATES),"GRADE_GATES")
    for expected,x in zip(HARD_GATES,g["hard_gates"]):closed(x,("gate","disposition"),"GRADE_GATE");require(x["gate"]==expected and x["disposition"] in ("PASS","FAIL"),"GRADE_GATE_ORDER")
    subjects=DIMENSIONS+("hard_gates",);require(isinstance(g["comments"],list) and len(g["comments"])==len(subjects),"GRADE_COMMENTS")
    for expected,x in zip(subjects,g["comments"]):closed(x,("subject","text"),"GRADE_COMMENT");require(x["subject"]==expected and isinstance(x["text"],str) and bool(x["text"].strip()),"GRADE_COMMENT_ORDER")
    packet_hashes=[x["canonical_content_sha256"] for x in p["refs"]];require(isinstance(g["evidence_refs"],list) and g["evidence_refs"]==packet_hashes,"GRADE_EXACT_PACKET_REFS")
    a=g["independence_attestation"];closed(a,("no_contact_with_other_graders","no_provider_identity_access","no_mapping_access","no_conflict_of_interest","attested_at_ms"),"GRADE_ATTEST");require(all(a[k] is True for k in ("no_contact_with_other_graders","no_provider_identity_access","no_mapping_access","no_conflict_of_interest")),"GRADE_NONINDEPENDENT");require(p["committed_at_ms"]<a["attested_at_ms"]<=g["produced_at_ms"],"GRADE_ATTEST_TIME")

def gap(a:str,b:str)->int:return abs(LEVELS.index(a)-LEVELS.index(b))
def g3_needed(a,b)->bool:
    ag,bg=gate_map(a),gate_map(b);ad,bd=dimension_map(a),dimension_map(b);return any(ag[x]!=bg[x] for x in HARD_GATES) or any(gap(ad[x],bd[x])>1 for x in DIMENSIONS)

def state_counts(items:Sequence[Mapping[str,Any]])->Tuple[int,int,int,int]:
    states=[]
    for x in items:
        closed(x,("id","state"),"STATE_ITEM");require(isinstance(x["id"],str) and bool(x["id"].strip()),"STATE_ID");require(x["state"] in ("CORRECT","WRONG","MISSING","UNKNOWN"),"STATE_VALUE");states.append(x["state"])
    require(len({x["id"] for x in items})==len(items),"STATE_DUPLICATE")
    return states.count("CORRECT"),states.count("WRONG"),states.count("MISSING"),states.count("UNKNOWN")
def ratio(items)->Dict[str,Any]:
    c,w,m,u=state_counts(items);den=len(items)
    return {"status":"UNKNOWN" if u else "NOT_APPLICABLE" if den==0 else "VALUE","numerator":c,"denominator":den,"wrong_count":w,"missing_count":m,"unknown_count":u,"value":None if u or den==0 else c/den}
def scalar(v:Mapping[str,Any],code:str):
    closed(v,("state","value"),code);require(v["state"] in ("VALUE","MISSING","UNKNOWN"),code+"_STATE")
    if v["state"]=="VALUE":require(isinstance(v["value"],(int,float)) and not isinstance(v["value"],bool) and v["value"]>=0,code+"_VALUE")
    else:require(v["value"] is None,code+"_NULL")

def validate_evidence(e:Mapping[str,Any],alias:str)->None:
    fields=("version","blind_alias","retained","freshness_items","richness_items","depth_items","accuracy_claims","citation_items","source_coverage_items","incremental_facts","provider_cost_usd","metered_tool_cost_usd","elapsed_ms","provider_time_ms","tool_time_ms")
    closed(e,fields,"EVIDENCE");require(e["version"]==3 and e["blind_alias"]==alias and e["retained"] is True,"EVIDENCE_ID")
    require(len(e["richness_items"])==60 and len(e["depth_items"])==6 and len(e["source_coverage_items"])==6,"EVIDENCE_DENOMINATORS")
    for k in ("freshness_items","richness_items","depth_items","accuracy_claims","citation_items","source_coverage_items"):state_counts(e[k])
    facts=e["incremental_facts"];seen=set()
    for x in facts:
        closed(x,("id","role","state"),"FACT");require(isinstance(x["id"],str) and bool(x["id"].strip()) and x["role"] in ("FACT","CONFLICT") and x["state"] in ("CORRECT","WRONG","MISSING","UNKNOWN"),"FACT_STATE");key=(x["role"],x["id"]);require(key not in seen,"FACT_DUPLICATE");seen.add(key)
    for k in ("provider_cost_usd","metered_tool_cost_usd","elapsed_ms","provider_time_ms","tool_time_ms"):scalar(e[k],k.upper())
def metric_scalar(values,kind,verified):
    for v in values:scalar(v,kind)
    miss=sum(v["state"]=="MISSING" for v in values);unk=sum(v["state"]=="UNKNOWN" for v in values)
    if unk or miss:return {"status":"UNKNOWN","numerator":None,"denominator":1,"wrong_count":0,"missing_count":miss,"unknown_count":unk,"value":None}
    total=sum(v["value"] for v in values);return {"status":"VALUE","numerator":total,"denominator":1,"wrong_count":0,"missing_count":0,"unknown_count":0,"value":total}
def derive_cell(e:Mapping[str,Any],cell:str,off:Mapping[str,Any]=None)->Dict[str,Any]:
    alias=ALIASES[cell];validate_evidence(e,alias);m={}
    m["freshness"]=ratio(e["freshness_items"]);m["richness"]=ratio(e["richness_items"]);m["depth"]=ratio(e["depth_items"]);m["accuracy"]=ratio(e["accuracy_claims"]);m["citation_accuracy"]=ratio(e["citation_items"]);m["source_coverage"]=ratio(e["source_coverage_items"])
    provider,addon=CELL_MAP[cell]
    if addon=="OFF":m["incremental_information_value"]={"status":"NOT_APPLICABLE","numerator":0,"denominator":0,"wrong_count":0,"missing_count":0,"unknown_count":0,"value":None,"false_new_fact_count":0,"signed_false_new_fact_count":0}
    else:
        require(off is not None,"INCREMENTAL_OFF_MISSING");validate_evidence(off,next(a for c,a in ALIASES.items() if CELL_MAP[c]==(provider,"OFF")))
        on={(x["role"],x["id"]):x["state"] for x in e["incremental_facts"]};base={(x["role"],x["id"]):x["state"] for x in off["incremental_facts"]};u=sum(v=="UNKNOWN" for v in list(on.values())+list(base.values()));ms=sum(v=="MISSING" for v in list(on.values())+list(base.values()));good_on={k for k,v in on.items() if v=="CORRECT"};good_off={k for k,v in base.items() if v=="CORRECT"};union=good_on|good_off;false_new={k for k,v in on.items() if v=="WRONG" and base.get(k)!="WRONG"};den=len(union)
        m["incremental_information_value"]={"status":"UNKNOWN" if u else "NOT_APPLICABLE" if den==0 else "VALUE","numerator":len(good_on-good_off),"denominator":den,"wrong_count":len(false_new),"missing_count":ms,"unknown_count":u,"value":None if u or den==0 else len(good_on-good_off)/den,"false_new_fact_count":len(false_new),"signed_false_new_fact_count":-len(false_new)}
    verified=state_counts(e["accuracy_claims"])
    m["cost"]=metric_scalar((e["provider_cost_usd"],e["metered_tool_cost_usd"]),"COST",verified)
    if verified[3]:pcs="UNKNOWN";pcv=None
    elif verified[0]==0:pcs="NOT_APPLICABLE";pcv=None
    elif m["cost"]["status"]!="VALUE":pcs="UNKNOWN";pcv=None
    else:pcs="VALUE";pcv=m["cost"]["value"]/verified[0]
    m["cost"].update(usd_per_correct_atomic_claim_status=pcs,usd_per_correct_atomic_claim=pcv)
    m["latency"]=metric_scalar((e["elapsed_ms"],),"LATENCY",verified);m["latency"].update(provider_time_ms=e["provider_time_ms"]["value"] if e["provider_time_ms"]["state"]=="VALUE" else None,tool_time_ms=e["tool_time_ms"]["value"] if e["tool_time_ms"]["state"]=="VALUE" else None)
    body={"version":3,"cell_id":cell,"evidence_content_sha256":sha256_json(e),"metrics":m,"immutable":True};return seal(body)
def contrast(vals,terms):
    x=[vals[c] for _,c in terms]
    if any(v["status"]=="UNKNOWN" for v in x):return {"status":"UNKNOWN","value":None,"formula":list(terms)}
    if any(v["status"]=="NOT_APPLICABLE" for v in x):return {"status":"NOT_APPLICABLE","value":None,"formula":list(terms)}
    return {"status":"VALUE","value":sum(w*vals[c]["value"] for w,c in terms),"formula":list(terms)}
def derive_block(ev:Mapping[str,Mapping[str,Any]])->Dict[str,Any]:
    require(tuple(ev)==CELL_ORDER,"BLOCK_EVIDENCE_ORDER");off={p:ev[c] for c,(p,a) in CELL_MAP.items() if a=="OFF"};arts={c:derive_cell(ev[c],c,off[CELL_MAP[c][0]] if CELL_MAP[c][1]=="ON" else None) for c in CELL_ORDER};cs={}
    terms={"provider_within_off":((1,CELL_ORDER[3]),(-1,CELL_ORDER[0])),"provider_within_on":((1,CELL_ORDER[1]),(-1,CELL_ORDER[2])),"addon_within_claude":((1,CELL_ORDER[2]),(-1,CELL_ORDER[0])),"addon_within_codex":((1,CELL_ORDER[1]),(-1,CELL_ORDER[3])),"provider_main_effect":((.5,CELL_ORDER[3]),(.5,CELL_ORDER[1]),(-.5,CELL_ORDER[0]),(-.5,CELL_ORDER[2])),"addon_main_effect":((.5,CELL_ORDER[2]),(.5,CELL_ORDER[1]),(-.5,CELL_ORDER[0]),(-.5,CELL_ORDER[3])),"interaction":((1,CELL_ORDER[1]),(-1,CELL_ORDER[3]),(-1,CELL_ORDER[2]),(1,CELL_ORDER[0]))}
    for d in DIMENSIONS:
        vals={c:arts[c]["metrics"][d] for c in CELL_ORDER};cs[d]={k:contrast(vals,t) for k,t in terms.items()}
    return seal({"version":3,"cell_metrics":arts,"contrasts":cs,"unknown_count":sum(v["unknown_count"] for a in arts.values() for v in a["metrics"].values()),"immutable":True})
def gate_from(store:ArtifactStore,p):
    ref=next(x for x in p["refs"] if x["kind"]=="deterministic_gate_report");g=store.read(ref);validate_intake("deterministic_gate_report",g,p["blind_alias"]);return g["hard_gates"]
def evidence_from(store,p):
    ref=next(x for x in p["refs"] if x["kind"]=="evidence_record");e=store.read(ref);validate_evidence(e,p["blind_alias"]);return e
def evaluate_cell(store,p,grades,authority):
    require(store.root_id()==authority.store.root_id(),"AUTHORITY_ROOT_SUBSTITUTION");validate_packet_runtime(store,p);roles=[g.get("grader_role") for g in grades];require(roles.count("G1")==1 and roles.count("G2")==1 and len(roles)==len(set(roles)),"G1_G2_REQUIRED");by={g["grader_role"]:g for g in grades}
    for g in grades:validate_grade(g,p,authority)
    require(by["G1"]["human_reviewer_id"]!=by["G2"]["human_reviewer_id"],"G1_G2_NONINDEPENDENT");need=g3_needed(by["G1"],by["G2"]);require(("G3" in by)==need,"G3_REQUIREMENT")
    if need:require(by["G3"]["human_reviewer_id"] not in (by["G1"]["human_reviewer_id"],by["G2"]["human_reviewer_id"]),"G3_NONINDEPENDENT")
    dg=gate_from(store,p)
    if need:
        for k,v in dg.items():require(not(v=="FAIL" and gate_map(by["G3"])[k]=="PASS"),"G3_HARD_GATE_OVERRIDE")
    final=dict(gate_map(by.get("G3",by["G1"])))
    for k,v in dg.items():
        if v=="FAIL":final[k]="FAIL"
    return {"status":"COMPLETE" if all(x=="PASS" for x in final.values()) else "HARD_GATE_FAIL","g3_required":need,"final_hard_gates":final,"latest_grade_at_ms":max(g["produced_at_ms"] for g in grades),"countable":authority.registry["countable"] and all(x=="PASS" for x in final.values())}
def authorize_unblinding(store,packets,grades,authority,mapping,nonce,opened_at_ms):
    require(tuple(packets)==CELL_ORDER and tuple(grades)==CELL_ORDER,"UNBLIND_FOUR_CELLS");expected={ALIASES[c]:{"cell_id":c,"provider":CELL_MAP[c][0],"addon":CELL_MAP[c][1]} for c in CELL_ORDER};require(mapping==expected,"UNBLIND_MAPPING")
    results={};ev={};latest=0;commit_ref=None;commit_value=None
    for c in CELL_ORDER:
        p=packets[c];validate_packet_runtime(store,p);require(p["blind_alias"]==ALIASES[c],"UNBLIND_ALIAS")
        if commit_ref is None:commit_ref=p["blind_map_commitment_ref"];commit_value=store.read(commit_ref);validate_map_commitment(commit_value)
        else:require(p["blind_map_commitment_ref"]==commit_ref and p["blind_map_commitment_content_sha256"]==commit_ref["canonical_content_sha256"],"UNBLIND_COMMITMENT_REF_DRIFT")
        results[c]=evaluate_cell(store,p,grades[c],authority);latest=max(latest,results[c]["latest_grade_at_ms"],p["committed_at_ms"]);ev[c]=evidence_from(store,p)
    require(commit_value["commitment_sha256"]==sha256_json({"mapping":mapping,"nonce":nonce}),"UNBLIND_COMMITMENT_OPENING");require(opened_at_ms>latest and opened_at_ms>commit_value["committed_at_ms"],"UNBLIND_EARLY")
    metrics=derive_block(ev);countable=authority.registry["countable"] and metrics["unknown_count"]==0 and all(x["countable"] for x in results.values())
    return seal({"version":3,"opened_at_ms":opened_at_ms,"mapping":mapping,"blind_map_commitment_content_sha256":commit_ref["canonical_content_sha256"],"block_metric":metrics,"cell_evaluations":results,"countable":countable,"status":"COUNTABLE" if countable else "FIXTURE_NOT_COUNTABLE" if authority.fixture else "INCONCLUSIVE_NOT_COUNTABLE","immutable":True})

