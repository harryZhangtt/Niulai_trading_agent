"""Owner-rooted, provider-free human-grade intake and evidence derivation v2."""
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
LEAK_TOKENS=("provider","model","addon","dq-layer","dq_layer","order","cost","latency","claude","codex","opus","gpt")
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
        require(ref["kind"] in REF_KINDS,"REF_KIND");raw_path=ref["path"]
        require(isinstance(raw_path,str) and raw_path,"REF_PATH")
        p=PurePosixPath(raw_path);require(not p.is_absolute() and ".." not in p.parts and "." not in p.parts,"REF_TRAVERSAL")
        low=raw_path.lower();require(not any(x in low for x in LEAK_TOKENS),"REF_PATH_LEAKAGE")
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
    names=("artifact-ref-v2.schema.json","blind-packet-v2.schema.json","evaluation-storage-v2.schema.json","grade-record-v2.schema.json","evidence-record-v2.schema.json","deterministic-gate-report-v2.schema.json","sanitized-output-v2.schema.json","source-inventory-v2.schema.json","citation-inventory-v2.schema.json","raw-custody-receipt-v2.schema.json")
    checked=[]
    for name in names:
        p=SCHEMA_DIR/name;require(p.is_file(),"PREFLIGHT_SCHEMA_MISSING");s=json.loads(p.read_text())
        require(s.get("$schema")=="https://json-schema.org/draft/2020-12/schema" and s.get("type")=="object" and s.get("additionalProperties") is False,"PREFLIGHT_SCHEMA_OPEN")
        require(set(s.get("required",()))<=set(s.get("properties",{})),"PREFLIGHT_SCHEMA_NESTED")
        checked.append({"path":name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size})
    closed(storage,("version","activation","provider_calls_permitted","root","atomic_create","no_replace","artifact_kinds"),"STORAGE")
    require(storage["version"]==2 and storage["activation"] is False and storage["provider_calls_permitted"] is False,"STORAGE_DISABLED")
    require(storage["atomic_create"] is True and storage["no_replace"] is True and set(storage["artifact_kinds"])>=set(REF_KINDS)|{"blind_packet","grade","metric","unblind"},"STORAGE_POLICY")
    ArtifactStore(Path(storage["root"]))
    return {"status":"PASS_PROVIDER_FREE_PREFLIGHT_V2","provider_calls_permitted":False,"schemas":checked}

def validate_intake(kind:str,value:Mapping[str,Any],alias:str)->None:
    if kind=="evidence_record":validate_evidence(value,alias);return
    if kind=="deterministic_gate_report":
        closed(value,("version","blind_alias","hard_gates"),"GATE_REPORT");require(value["version"]==2 and value["blind_alias"]==alias and set(value["hard_gates"])==set(HARD_GATES) and all(x in ("PASS","FAIL") for x in value["hard_gates"].values()),"GATE_REPORT_VALUE");return
    if kind=="sanitized_output":closed(value,("version","blind_alias","text"),"SANITIZED_OUTPUT")
    elif kind=="source_inventory":
        closed(value,("version","blind_alias","sources"),"SOURCE_INVENTORY")
        for x in value["sources"]:closed(x,("id","url","cutoff_ok"),"SOURCE_ITEM")
    elif kind=="citation_inventory":
        closed(value,("version","blind_alias","citations"),"CITATION_INVENTORY")
        for x in value["citations"]:closed(x,("id","source_id","claim_id"),"CITATION_ITEM")
    elif kind=="raw_custody_receipt":closed(value,("version","blind_alias","raw_sha256","owner_private"),"CUSTODY")
    else:raise ContractError("INTAKE_KIND")
    require(value["version"]==2 and value["blind_alias"]==alias,"INTAKE_ID")
    if kind=="raw_custody_receipt":require(value["owner_private"] is True and bool(SHA.fullmatch(str(value["raw_sha256"]))),"CUSTODY_VALUE")

def build_blind_packet(store: ArtifactStore, blind_alias: str, refs: Sequence[Mapping[str,Any]], committed_at_ms:int, masking_breach:bool=False)->Dict[str,Any]:
    require(blind_alias in ALIASES.values(),"PACKET_ALIAS");require(isinstance(committed_at_ms,int) and committed_at_ms>0,"PACKET_TIME")
    by={}
    for ref in refs:
        value=store.read(ref);kind=ref["kind"];validate_intake(kind,value,blind_alias);require(kind not in by,"PACKET_REF_DUPLICATE");require(ref["immutable_at_ms"]<=committed_at_ms,"PACKET_REF_AFTER_COMMIT");by[kind]=(dict(ref),value)
    require(set(by)==set(REF_KINDS),"PACKET_REF_MISSING")
    # Enforce each sanitized artifact's closed v2 identity before it reaches a grader.
    require(by["evidence_record"][1].get("version")==2 and by["evidence_record"][1].get("blind_alias")==blind_alias,"PACKET_EVIDENCE_ID")
    require(by["deterministic_gate_report"][1].get("version")==2 and by["deterministic_gate_report"][1].get("blind_alias")==blind_alias,"PACKET_GATE_ID")
    body={"version":2,"packet_id":"packet/"+blind_alias,"blind_alias":blind_alias,"artifact_root_id":store.root_id(),"refs":[by[k][0] for k in REF_KINDS],"refs_sha256":sha256_json([by[k][0] for k in REF_KINDS]),"committed_at_ms":committed_at_ms,"masking_breach":bool(masking_breach),"immutable":True}
    return seal(body)

def seal_grade(record: Mapping[str,Any])->Dict[str,Any]:
    require("artifact_sha256" not in record and "artifact_bytes" not in record,"GRADE_ALREADY_SEALED");b=dict(record);b["immutable"]=True;return seal(b)
def validate_grade(g:Mapping[str,Any],p:Mapping[str,Any],fixture:bool=False)->None:
    fields=("version","grade_id","cell_blind_alias","packet_sha256","packet_refs_sha256","grader_role","reviewer_kind","human_reviewer_id","blind","countable","dimensions","hard_gates","evidence_refs","comments","independence_attestation","packet_committed_at_ms","produced_at_ms","immutable","artifact_sha256","artifact_bytes")
    closed(g,fields,"GRADE");verify_seal(g,"GRADE");verify_seal(p,"PACKET")
    require(g["version"]==2 and g["grader_role"] in ("G1","G2","G3"),"GRADE_ROLE");require(g["cell_blind_alias"]==p["blind_alias"] and g["packet_sha256"]==p["artifact_sha256"] and g["packet_refs_sha256"]==p["refs_sha256"],"GRADE_PACKET_BINDING")
    require(g["packet_committed_at_ms"]==p["committed_at_ms"] and isinstance(g["produced_at_ms"],int) and g["produced_at_ms"]>p["committed_at_ms"],"GRADE_PREPACKET")
    require(g["blind"] is True,"GRADE_BLIND")
    if fixture:require(g["reviewer_kind"]=="FIXTURE_HUMAN" and g["countable"] is False,"FIXTURE_GRADE")
    else:require(g["reviewer_kind"]=="HUMAN" and g["countable"] is True,"LIVE_FAKE_HUMAN_FORBIDDEN")
    require(set(g["dimensions"])==set(DIMENSIONS) and all(x in LEVELS for x in g["dimensions"].values()),"GRADE_DIMENSIONS")
    require(set(g["hard_gates"])==set(HARD_GATES) and all(x in ("PASS","FAIL") for x in g["hard_gates"].values()),"GRADE_GATES")
    require(set(g["comments"])==set(DIMENSIONS+("hard_gates",)) and all(isinstance(x,str) and x.strip() for x in g["comments"].values()),"GRADE_COMMENTS")
    packet_hashes={x["canonical_content_sha256"] for x in p["refs"]};require(isinstance(g["evidence_refs"],list) and set(g["evidence_refs"])==packet_hashes,"GRADE_EXACT_PACKET_REFS")
    a=g["independence_attestation"];closed(a,("no_contact_with_other_graders","no_provider_identity_access","no_mapping_access","no_conflict_of_interest","attested_at_ms"),"GRADE_ATTEST");require(all(a[k] is True for k in list(a)[:-1]),"GRADE_NONINDEPENDENT");require(p["committed_at_ms"]<a["attested_at_ms"]<=g["produced_at_ms"],"GRADE_ATTEST_TIME")
def gap(a:str,b:str)->int:return abs(LEVELS.index(a)-LEVELS.index(b))
def g3_needed(a,b)->bool:return any(a["hard_gates"][x]!=b["hard_gates"][x] for x in HARD_GATES) or any(gap(a["dimensions"][x],b["dimensions"][x])>1 for x in DIMENSIONS)

def state_counts(items:Sequence[Mapping[str,Any]])->Tuple[int,int,int,int]:
    states=[]
    for x in items:
        closed(x,("id","state"),"STATE_ITEM");require(isinstance(x["id"],str) and x["id"],"STATE_ID");require(x["state"] in ("CORRECT","WRONG","MISSING","UNKNOWN"),"STATE_VALUE");states.append(x["state"])
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
    closed(e,fields,"EVIDENCE");require(e["version"]==2 and e["blind_alias"]==alias and e["retained"] is True,"EVIDENCE_ID")
    require(len(e["richness_items"])==60 and len(e["depth_items"])==6 and len(e["source_coverage_items"])==6,"EVIDENCE_DENOMINATORS")
    for k in ("freshness_items","richness_items","depth_items","accuracy_claims","citation_items","source_coverage_items"):state_counts(e[k])
    facts=e["incremental_facts"];seen=set()
    for x in facts:
        closed(x,("id","role","state"),"FACT");require(x["role"] in ("FACT","CONFLICT") and x["state"] in ("CORRECT","WRONG","MISSING","UNKNOWN"),"FACT_STATE");require(x["id"] not in seen,"FACT_DUPLICATE");seen.add(x["id"])
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
        on={x["id"]:x["state"] for x in e["incremental_facts"]};base={x["id"]:x["state"] for x in off["incremental_facts"]};u=sum(v=="UNKNOWN" for v in list(on.values())+list(base.values()));ms=sum(v=="MISSING" for v in list(on.values())+list(base.values()));good_on={k for k,v in on.items() if v=="CORRECT"};good_off={k for k,v in base.items() if v=="CORRECT"};union=good_on|good_off;false_new={k for k,v in on.items() if v=="WRONG" and base.get(k)!="WRONG"};den=len(union)
        m["incremental_information_value"]={"status":"UNKNOWN" if u else "NOT_APPLICABLE" if den==0 else "VALUE","numerator":len(good_on-good_off),"denominator":den,"wrong_count":len(false_new),"missing_count":ms,"unknown_count":u,"value":None if u or den==0 else len(good_on-good_off)/den,"false_new_fact_count":len(false_new),"signed_false_new_fact_count":-len(false_new)}
    verified=state_counts(e["accuracy_claims"])
    m["cost"]=metric_scalar((e["provider_cost_usd"],e["metered_tool_cost_usd"]),"COST",verified)
    if verified[3]:pcs="UNKNOWN";pcv=None
    elif verified[0]==0:pcs="NOT_APPLICABLE";pcv=None
    elif m["cost"]["status"]!="VALUE":pcs="UNKNOWN";pcv=None
    else:pcs="VALUE";pcv=m["cost"]["value"]/verified[0]
    m["cost"].update(usd_per_correct_atomic_claim_status=pcs,usd_per_correct_atomic_claim=pcv)
    m["latency"]=metric_scalar((e["elapsed_ms"],),"LATENCY",verified);m["latency"].update(provider_time_ms=e["provider_time_ms"]["value"] if e["provider_time_ms"]["state"]=="VALUE" else None,tool_time_ms=e["tool_time_ms"]["value"] if e["tool_time_ms"]["state"]=="VALUE" else None)
    body={"version":2,"cell_id":cell,"evidence_content_sha256":sha256_json(e),"metrics":m,"immutable":True};return seal(body)
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
    return seal({"version":2,"cell_metrics":arts,"contrasts":cs,"unknown_count":sum(v["unknown_count"] for a in arts.values() for v in a["metrics"].values()),"immutable":True})
def gate_from(store:ArtifactStore,p):
    ref=next(x for x in p["refs"] if x["kind"]=="deterministic_gate_report");g=store.read(ref);validate_intake("deterministic_gate_report",g,p["blind_alias"]);return g["hard_gates"]
def evidence_from(store,p):
    ref=next(x for x in p["refs"] if x["kind"]=="evidence_record");e=store.read(ref);validate_evidence(e,p["blind_alias"]);return e
def evaluate_cell(store,p,grades,fixture=False):
    verify_seal(p,"PACKET");require(p["artifact_root_id"]==store.root_id(),"PACKET_ROOT_SUBSTITUTION")
    for ref in p["refs"]:store.read(ref)
    roles=[g.get("grader_role") for g in grades];require(roles.count("G1")==1 and roles.count("G2")==1 and len(roles)==len(set(roles)),"G1_G2_REQUIRED");by={g["grader_role"]:g for g in grades}
    for g in grades:validate_grade(g,p,fixture)
    require(by["G1"]["human_reviewer_id"]!=by["G2"]["human_reviewer_id"],"G1_G2_NONINDEPENDENT");need=g3_needed(by["G1"],by["G2"]);require(("G3" in by)==need,"G3_REQUIREMENT")
    if need:require(by["G3"]["human_reviewer_id"] not in (by["G1"]["human_reviewer_id"],by["G2"]["human_reviewer_id"]),"G3_NONINDEPENDENT")
    dg=gate_from(store,p)
    if need:
        for k,v in dg.items():require(not(v=="FAIL" and by["G3"]["hard_gates"][k]=="PASS"),"G3_HARD_GATE_OVERRIDE")
    final=dict(by.get("G3",by["G1"])["hard_gates"])
    for k,v in dg.items():
        if v=="FAIL":final[k]="FAIL"
    return {"status":"COMPLETE" if all(x=="PASS" for x in final.values()) else "HARD_GATE_FAIL","g3_required":need,"final_hard_gates":final,"latest_grade_at_ms":max(g["produced_at_ms"] for g in grades),"countable":not fixture and all(x=="PASS" for x in final.values())}
def authorize_unblinding(store,packets,grades,mapping,nonce,commitment,opened_at_ms,fixture=False):
    require(tuple(packets)==CELL_ORDER and tuple(grades)==CELL_ORDER,"UNBLIND_FOUR_CELLS");expected={ALIASES[c]:{"cell_id":c,"provider":CELL_MAP[c][0],"addon":CELL_MAP[c][1]} for c in CELL_ORDER};require(mapping==expected and commitment==sha256_json({"mapping":mapping,"nonce":nonce}),"UNBLIND_COMMITMENT")
    results={};ev={};latest=0
    for c in CELL_ORDER:
        p=packets[c];require(p["blind_alias"]==ALIASES[c],"UNBLIND_ALIAS");results[c]=evaluate_cell(store,p,grades[c],fixture);latest=max(latest,results[c]["latest_grade_at_ms"],p["committed_at_ms"]);ev[c]=evidence_from(store,p)
    require(opened_at_ms>latest,"UNBLIND_EARLY");metrics=derive_block(ev);countable=not fixture and metrics["unknown_count"]==0 and all(x["countable"] for x in results.values())
    return seal({"version":2,"opened_at_ms":opened_at_ms,"mapping":mapping,"commitment_sha256":commitment,"block_metric":metrics,"cell_evaluations":results,"countable":countable,"status":"COUNTABLE" if countable else "FIXTURE_NOT_COUNTABLE" if fixture else "INCONCLUSIVE_NOT_COUNTABLE","immutable":True})
