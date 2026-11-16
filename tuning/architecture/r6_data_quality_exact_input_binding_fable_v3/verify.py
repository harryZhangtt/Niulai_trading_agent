#!/usr/bin/env python3
"""Owner-bound, transitively closed verifier for R6 exact-input binding v3."""
from __future__ import annotations
import copy, hashlib, json, os, re, shutil, stat, sys, tempfile, unicodedata
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Sequence

ROOT=Path(__file__).resolve().parents[3];PACKAGE=Path(__file__).resolve().parent
MANIFEST=PACKAGE/"current-input-manifest-v3.json";SCHEMA=PACKAGE/"input-manifest-v3.schema.json"
UID=501;ALLOWED_ROOT="mentor/runtime/scheduler-midresponse-recovery-20261107"
COMMON_BYTES=6172;COMMON_SHA="649dd0b9b0df4dfd8dccda01751a97ea6b943396acaef4aa5f1747c2ae33a5c4"
PROMPT_SHA="3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"
CELLS={"R6DQ-7F2C91A4","R6DQ-1B8E43D7","R6DQ-C4A7095E","R6DQ-92D6F0B3"}
ROOT_COMPONENTS={"mentor":{"mode":"0755","owner_uid":UID},"mentor/runtime":{"mode":"0755","owner_uid":UID},ALLOWED_ROOT:{"mode":"0700","owner_uid":UID}}
EXPECTED={
"payload":{"path":ALLOWED_ROOT+"/schema9-isolated-canary-q1-ab-payload-v1.json","mode":"0644","owner_uid":UID,"bytes":2065,"sha256":"26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a","content_sha256":"b1941934d2aa879c52e42bbce5b2d0c49001732342aa5f6b25f1dc6c66b2cd5c"},
"source_cutoff":{"path":ALLOWED_ROOT+"/schema9-isolated-canary-q1-ab-source-cutoff-v1.json","mode":"0644","owner_uid":UID,"bytes":1044,"sha256":"32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072","content_sha256":"2c4f69d233e90b7047dbf23d70167a5e4d59366a4d83ea1a1aa959ec06633f9c"},
"rubric":{"path":ALLOWED_ROOT+"/schema9-isolated-canary-q1-ab-rubric.json","mode":"0600","owner_uid":UID,"bytes":2259,"sha256":"81069b2ce57f30e56d70e7a2edd4672991838ebce1e2369b48effb8adde53d8f","content_sha256":"35c155ab610cdc8bb6dc9ea639fce16ca51256b5703b99d0849279831685f790"},
"thresholds":{"path":ALLOWED_ROOT+"/schema9-isolated-canary-q1-ab-thresholds-v2.json","mode":"0644","owner_uid":UID,"bytes":3597,"sha256":"41bbb8c07c26aadb9fe0e795b1ac8e5d3a17c88d60cba77692845b135dd4b95b","content_sha256":"98ca21509f9a920f42fa79bda31696023422575d49040070c696519183e1d8e9"},
"evaluation_schema":{"path":ALLOWED_ROOT+"/schema9-isolated-canary-q1-ab-evidence-schema.json","mode":"0600","owner_uid":UID,"bytes":1876,"sha256":"8f28c800b70c968af9ee02ec8ddbd897d33a253474273d20e7f9f5b4868b74d5","content_sha256":"cafbfe18e695e4dfa2ff9bf2cfab0d0b29ff89c8e58a34bf3c42f8c9a6676f9c"},
"entry_packet":{"path":ALLOWED_ROOT+"/schema9-isolated-canary-q1-ab-entry-packet.json","mode":"0644","owner_uid":UID,"bytes":4756,"sha256":"398abd1b7c512eb3c7eb8eec210c8b1eaa43c8318cb08838a20194a18a1e676b","content_sha256":"3d4ba96fbb98f680262bc7ee16f11ef27c479c79dc411fe53f6e41508222d5f7"},
"user_decision":{"path":ALLOWED_ROOT+"/schema9-isolated-canary-q1-ab-user-decision-receipt.json","mode":"0644","owner_uid":UID,"bytes":633,"sha256":"0b86722bf9c65fd068af8d4f16dd931bd0c8fc18e585842d382f0063f42e5d30","content_sha256":"290b82365cf42b1e39cbd17f574f52a80124a5dc711692453745efcd348feca7"}}
EDGE_TUPLES=[("evaluation_schema","/packet","PATH_BYTES_HASH","entry_packet"),("payload","/bindings/evidence_schema_sha256","HASH_ONLY","evaluation_schema"),("payload","/bindings/packet_sha256","HASH_ONLY","entry_packet"),("payload","/bindings/rubric_sha256","HASH_ONLY","rubric"),("payload","/bindings/thresholds_v2_sha256","HASH_ONLY","thresholds"),("payload","/source_cutoff","PATH_BYTES_HASH","source_cutoff"),("rubric","/packet","PATH_BYTES_HASH","entry_packet"),("thresholds","/bindings/schema9-isolated-canary-q1-ab-entry-packet.json","PATH_BYTES_HASH","entry_packet"),("thresholds","/bindings/schema9-isolated-canary-q1-ab-evidence-schema.json","PATH_BYTES_HASH","evaluation_schema"),("thresholds","/bindings/schema9-isolated-canary-q1-ab-rubric.json","PATH_BYTES_HASH","rubric"),("thresholds","/bindings/user_decision","PATH_BYTES_HASH","user_decision")]
EXPECTED_EDGES=[{"source":s,"json_pointer":p,"kind":k,"target":t,"target_sha256":EXPECTED[t]["sha256"]} for s,p,k,t in EDGE_TUPLES]
LOCAL=[{"source":"payload","json_pointer":"/payload_sha256","kind":"PROMPT_UTF8_SHA256","bytes_pointer":"/payload_bytes","value_pointer":"/prompt_utf8","expected_sha256":PROMPT_SHA,"expected_bytes":526}]
LEAK=frozenset(("provider","model","addon","order","private","internal","claude","codex","opus","gpt","fable","sonnet","haiku","treatment","baseline","layer","dq","on","off","sol"));SHA=re.compile(r"^[0-9a-f]{64}$")
class VerificationError(ValueError):pass
def require(v:bool,code:str)->None:
 if not v:raise VerificationError(code)
def strict_loads(raw:bytes)->Any:
 require(not raw.startswith(b"\xef\xbb\xbf"),"UTF8_BOM")
 try:text=raw.decode("utf-8","strict")
 except UnicodeDecodeError as e:raise VerificationError("UTF8_INVALID") from e
 def hook(pairs):
  out={}
  for k,v in pairs:require(k not in out,"JSON_DUPLICATE:"+k);out[k]=v
  return out
 def bad(v):raise VerificationError("JSON_NONFINITE:"+v)
 try:return json.loads(text,object_pairs_hook=hook,parse_constant=bad)
 except VerificationError:raise
 except (json.JSONDecodeError,TypeError,ValueError) as e:raise VerificationError("JSON_INVALID") from e
def strict_load(p:Path)->Any:return strict_loads(p.read_bytes())
def canonical_bytes(v:Any)->bytes:
 try:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
 except (TypeError,ValueError,UnicodeError) as e:raise VerificationError("CANONICAL_INVALID") from e
def digest(v:Any)->str:return hashlib.sha256(canonical_bytes(v)).hexdigest()
def resolve_ref(root,ref):
 require(ref.startswith("#/"),"SCHEMA_REF_EXTERNAL");cur=root
 for part in ref[2:].split("/"):require(isinstance(cur,Mapping) and part in cur,"SCHEMA_REF_MISSING");cur=cur[part]
 require(isinstance(cur,Mapping),"SCHEMA_REF_OBJECT");return cur
def validate_schema(v,schema,root,path="$"):
 if "$ref" in schema:validate_schema(v,resolve_ref(root,schema["$ref"]),root,path);return
 if "const" in schema:require(v==schema["const"],"SCHEMA_CONST:"+path)
 if "enum" in schema:require(v in schema["enum"],"SCHEMA_ENUM:"+path)
 t=schema.get("type")
 if t=="object":
  require(isinstance(v,dict),"SCHEMA_OBJECT:"+path);req=set(schema.get("required",[]));require(req<=set(v),"SCHEMA_REQUIRED:"+path);props=schema.get("properties",{})
  if schema.get("additionalProperties") is False:require(set(v)<=set(props),"SCHEMA_EXTRA:"+path)
  for k,x in v.items():
   if k in props:validate_schema(x,props[k],root,path+"."+k)
 elif t=="array":
  require(isinstance(v,list),"SCHEMA_ARRAY:"+path);require(len(v)>=schema.get("minItems",0),"SCHEMA_MIN_ITEMS:"+path)
  if "maxItems" in schema:require(len(v)<=schema["maxItems"],"SCHEMA_MAX_ITEMS:"+path)
  for i,x in enumerate(v):validate_schema(x,schema.get("items",{}),root,f"{path}[{i}]")
 elif t=="string":require(isinstance(v,str),"SCHEMA_STRING:"+path)
 elif t=="integer":require(isinstance(v,int) and not isinstance(v,bool),"SCHEMA_INTEGER:"+path)
 elif t=="boolean":require(isinstance(v,bool),"SCHEMA_BOOLEAN:"+path)
def tokens(p):return set(re.findall(r"[a-z0-9]+",unicodedata.normalize("NFKC",p).casefold()))
def validate_locator(path,expected):
 require(isinstance(path,str) and path.isascii(),"PATH_ASCII");require(unicodedata.normalize("NFC",path)==path and unicodedata.normalize("NFKC",path)==path,"PATH_NORMALIZATION")
 require("\\" not in path and "//" not in path and not path.startswith("/"),"PATH_LEXICAL");pure=PurePosixPath(path);require(not pure.is_absolute() and all(x not in ("",".","..") for x in path.split("/")),"PATH_COMPONENT")
 require(tuple(pure.parts)==tuple(path.split("/")) and path==expected and path==path.casefold(),"PATH_NOT_EXACT");require(not(tokens(path)&LEAK),"PATH_LABEL_LEAK");require(path.startswith(ALLOWED_ROOT+"/"),"PATH_ROOT")
def verify_workspace_root_stat(st,uid):require(stat.S_ISDIR(st.st_mode) and st.st_uid==uid,"WORKSPACE_ROOT_OWNER")
def verify_component_stat(st,uid,mode):require(stat.S_ISDIR(st.st_mode) and st.st_uid==uid and stat.S_IMODE(st.st_mode)==mode,"ROOT_COMPONENT_OWNER_MODE")
def verify_final_stat(st,uid,mode):require(stat.S_ISREG(st.st_mode) and st.st_uid==uid and stat.S_IMODE(st.st_mode)==mode,"FINAL_OWNER_MODE_TYPE")
def secure_read(ref,identity):
 trusted=identity["trusted_process_uid"];require(identity["owner_uid"]==trusted==UID==os.getuid(),"TRUSTED_PROCESS_UID")
 flags=os.O_RDONLY|getattr(os,"O_CLOEXEC",0);nofollow=getattr(os,"O_NOFOLLOW",0);directory=getattr(os,"O_DIRECTORY",0);require(nofollow and directory,"NOFOLLOW_UNAVAILABLE")
 lst=os.lstat(ROOT);require(not stat.S_ISLNK(lst.st_mode),"WORKSPACE_ROOT_SYMLINK");verify_workspace_root_stat(lst,trusted)
 fd=os.open(str(ROOT),flags|directory|nofollow)
 try:
  verify_workspace_root_stat(os.fstat(fd),trusted);walk=[];parts=ref["path"].split("/")
  for part in parts[:-1]:
   walk.append(part);child=os.open(part,flags|directory|nofollow,dir_fd=fd);os.close(fd);fd=child;rel="/".join(walk);require(rel in identity["root_components"],"UNBOUND_ROOT_COMPONENT");pin=identity["root_components"][rel];verify_component_stat(os.fstat(fd),pin["owner_uid"],int(pin["mode"],8))
  final=os.open(parts[-1],flags|nofollow,dir_fd=fd)
  try:
   verify_final_stat(os.fstat(final),ref["owner_uid"],int(ref["mode"],8));chunks=[]
   while True:
    b=os.read(final,65536)
    if not b:break
    chunks.append(b)
   return b"".join(chunks)
  finally:os.close(final)
 except OSError as e:raise VerificationError("NOFOLLOW_OPEN") from e
 finally:
  try:os.close(fd)
  except OSError:pass
def pointer_get(v,p):
 cur=v
 for part in p.split("/")[1:]:
  key=part.replace("~1","/").replace("~0","~");cur=cur[int(key)] if isinstance(cur,list) else cur[key]
 return cur
def discover_claims(artifacts):
 claims=[]
 def walk(source,v,p=""):
  if isinstance(v,dict):
   if {"path","sha256","bytes"}<=set(v):claims.append(("object_ref",source,p))
   for k,x in v.items():
    child=p+"/"+k.replace("~","~0").replace("/","~1")
    if isinstance(x,str) and SHA.fullmatch(x) and (k=="sha256" or k.endswith("_sha256")):claims.append(("hash_leaf",source,child))
    walk(source,x,child)
  elif isinstance(v,list):
   for i,x in enumerate(v):walk(source,x,p+"/"+str(i))
 for source,value in artifacts.items():walk(source,value)
 return set(claims)
def audit_semantic_closure(identity,artifacts):
 require(identity["semantic_dependencies"]==EXPECTED_EDGES and identity["local_content_claims"]==LOCAL,"DEPENDENCY_REGISTRY")
 expected=set()
 for e in EXPECTED_EDGES:
  target=identity["artifacts"][e["target"]];value=pointer_get(artifacts[e["source"]],e["json_pointer"])
  if e["kind"]=="HASH_ONLY":require(value==target["sha256"]==e["target_sha256"],"DEPENDENCY_HASH");expected.add(("hash_leaf",e["source"],e["json_pointer"]))
  else:require(value=={"path":target["path"],"sha256":target["sha256"],"bytes":target["bytes"]},"DEPENDENCY_REF");expected.add(("object_ref",e["source"],e["json_pointer"]));expected.add(("hash_leaf",e["source"],e["json_pointer"]+"/sha256"))
 local=LOCAL[0];payload=artifacts["payload"];prompt=pointer_get(payload,local["value_pointer"]).encode();require(len(prompt)==pointer_get(payload,local["bytes_pointer"])==local["expected_bytes"] and hashlib.sha256(prompt).hexdigest()==pointer_get(payload,local["json_pointer"])==local["expected_sha256"],"LOCAL_PROMPT_CLAIM");expected.add(("hash_leaf","payload","/payload_sha256"))
 discovered=discover_claims(artifacts);require(discovered==expected,"RECURSIVE_CLAIM_COVERAGE");return len(discovered)
def scan_paths(v,key=""):
 if isinstance(v,Mapping):
  for k,x in v.items():scan_paths(x,k)
 elif isinstance(v,list):
  for x in v:scan_paths(x,key)
 elif isinstance(v,str) and key in ("path","normalized_path"):require(not(tokens(v)&LEAK),"MANIFEST_PATH_LEAK")
def validate_semantics(a):
 payload=a["payload"];cutoff=a["source_cutoff"];prompt=payload["prompt_utf8"].encode();require((len(prompt),hashlib.sha256(prompt).hexdigest())==(526,PROMPT_SHA),"PROMPT")
 require(cutoff["cutoff_at"]=="2026-11-09T00:00:00Z" and len(cutoff["allowed_sources"])==2 and all("official" in x.lower() for x in cutoff["allowed_sources"]),"SOURCE_CUTOFF")
 require(a["entry_packet"]["status"]=="DESIGN_ONLY_NO_LIVE_AUTHORITY" and a["user_decision"]["status"]=="SANITIZED_DESIGN_DECISION_ONLY","TRANSITIVE_STATUS")
 bad=("financial return","investment return","pnl","profit","sharpe","sortino","claude","codex","gpt","opus")
 require(not any(x in json.dumps(a["rubric"]).lower() for x in bad) and not any(x in json.dumps(a["thresholds"]).lower() for x in bad),"RETURN_PROVIDER_PREFERENCE")
def validate_manifest(m,check_mode=True):
 schema=strict_load(SCHEMA);validate_schema(m,schema,schema);scan_paths(m)
 if check_mode:
  ps=os.lstat(PACKAGE);ms=os.lstat(MANIFEST);require(stat.S_ISDIR(ps.st_mode) and ps.st_uid==UID and stat.S_IMODE(ps.st_mode)==0o700,"PACKAGE_PRIVATE");require(stat.S_ISREG(ms.st_mode) and ms.st_uid==UID and stat.S_IMODE(ms.st_mode)==0o600,"MANIFEST_PRIVATE")
 identity=m["common_binding"]["identity"];require(identity["owner_uid"]==identity["trusted_process_uid"]==UID==os.getuid(),"BOUND_UID");require(identity["root_components"]==ROOT_COMPONENTS,"ROOT_BINDINGS")
 artifacts={};rebuilt={}
 for name,expected in EXPECTED.items():
  ref=identity["artifacts"][name];validate_locator(ref["path"],expected["path"]);require(ref["normalized_path"]==ref["path"] and ref["owner_uid"]==expected["owner_uid"] and ref["mode"]==expected["mode"],"REF_IDENTITY")
  raw=secure_read(ref,identity);require(len(raw)==ref["bytes"]==expected["bytes"] and hashlib.sha256(raw).hexdigest()==ref["sha256"]==expected["sha256"],"REF_RAW:"+name);value=strict_loads(raw);require(digest(value)==ref["content_sha256"]==expected["content_sha256"],"REF_CONTENT:"+name);artifacts[name]=value;rebuilt[name]=copy.deepcopy(ref)
 observed={"owner_uid":UID,"trusted_process_uid":UID,"allowed_root":ALLOWED_ROOT,"root_components":ROOT_COMPONENTS,"artifacts":rebuilt,"semantic_dependencies":EXPECTED_EDGES,"local_content_claims":LOCAL};require(observed==identity,"IDENTITY_REBUILD");claims=audit_semantic_closure(identity,artifacts)
 require((len(canonical_bytes(identity)),digest(identity))==(m["common_binding"]["canonical_utf8_bytes"],m["common_binding"]["canonical_sha256"])==(COMMON_BYTES,COMMON_SHA),"COMMON_DIGEST")
 require(set(m["cell_bindings"])==CELLS and len({canonical_bytes(x) for x in m["cell_bindings"].values()})==1 and all(x==m["common_binding"] for x in m["cell_bindings"].values()),"CELL_IDENTITY")
 require([x["pin"] for x in m["unresolved_pins"]]==["tool_roster","time_window","final_grants"],"PINS");require(m["countable"] is False and not any(m["effects"].values()) and not any(m["dependencies"].values()),"EFFECTS");validate_semantics(artifacts)
 return {"common_binding":{"canonical_utf8_bytes":COMMON_BYTES,"canonical_sha256":COMMON_SHA,"owner_uid":UID},"artifacts":len(artifacts),"recursive_reference_claims":claims}
def expect_failure(name,fn):
 try:fn()
 except (VerificationError,UnicodeError,ValueError,TypeError,OSError,KeyError):return "PASS_DENIED"
 raise AssertionError("adversary accepted: "+name)
def reseal(m,identity):
 bad=copy.deepcopy(m);b=canonical_bytes(identity);bad["common_binding"]={"canonical_utf8_bytes":len(b),"canonical_sha256":hashlib.sha256(b).hexdigest(),"identity":identity}
 for c in bad["cell_bindings"]:bad["cell_bindings"][c]=copy.deepcopy(bad["common_binding"])
 return bad
def run_adversaries(m):
 r={};r["duplicate_key"]=expect_failure("duplicate",lambda:strict_loads(b'{"x":1,"x":2}'));r["invalid_utf8"]=expect_failure("utf8",lambda:strict_loads(b'{"x":"\xff"}'));r["nonfinite"]=expect_failure("nan",lambda:strict_loads(b'{"x":NaN}'))
 expected=EXPECTED["payload"]["path"];source=ROOT/expected;tmp=Path(tempfile.mkdtemp(prefix="adversary-",dir=PACKAGE));os.chmod(tmp,0o700)
 try:
  cp=tmp/"payload.json";shutil.copyfile(source,cp);os.chmod(cp,0o600);rel=cp.relative_to(ROOT).as_posix();r["same_byte_absolute"]=expect_failure("abs",lambda:validate_locator(str(cp),expected));r["alternate_relative"]=expect_failure("alt",lambda:validate_locator(rel,expected))
  lab=tmp/"claude-model-addon-order-private-internal";lab.mkdir(mode=0o700);lf=lab/"payload.json";shutil.copyfile(source,lf);os.chmod(lf,0o600);lrel=lf.relative_to(ROOT).as_posix();r["labeled_relative"]=expect_failure("label",lambda:validate_locator(lrel,expected))
  sy=tmp/"alias.json";sy.symlink_to(source);ref=copy.deepcopy(m["common_binding"]["identity"]["artifacts"]["payload"]);ref["path"]=sy.relative_to(ROOT).as_posix();ref["mode"]="0644";r["symlink_alias"]=expect_failure("symlink",lambda:secure_read(ref,m["common_binding"]["identity"]))
  r["case_variant"]=expect_failure("case",lambda:validate_locator("Mentor/"+expected.split("/",1)[1],expected));r["normalization_variant"]=expect_failure("norm",lambda:validate_locator(expected.replace("mentor","mentｏr",1),expected));r["traversal"]=expect_failure("trav",lambda:validate_locator(ALLOWED_ROOT+"/../x.json",expected))
  ident=copy.deepcopy(m["common_binding"]["identity"]);ident["artifacts"]["payload"]["owner_uid"]=777;bad=reseal(m,ident);require(bad["common_binding"]["canonical_sha256"]!=COMMON_SHA,"OWNER_DIGEST");r["owner_ref_reseal"]=expect_failure("owner_ref",lambda:validate_manifest(bad,False))
  ident=copy.deepcopy(m["common_binding"]["identity"]);ident["owner_uid"]=ident["trusted_process_uid"]=777
  for x in ident["root_components"].values():x["owner_uid"]=777
  for x in ident["artifacts"].values():x["owner_uid"]=777
  bad=reseal(m,ident);require(bad["common_binding"]["canonical_sha256"]!=COMMON_SHA,"ROOT_OWNER_DIGEST");r["different_uid_root_reseal"]=expect_failure("root_uid",lambda:validate_manifest(bad,False))
  fake=SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=777);r["different_uid_root_stat"]=expect_failure("root_stat",lambda:verify_workspace_root_stat(fake,UID));fakef=SimpleNamespace(st_mode=stat.S_IFREG|0o644,st_uid=777);r["different_uid_final_stat"]=expect_failure("final_stat",lambda:verify_final_stat(fakef,UID,0o644))
  for target in ("entry_packet","user_decision"):
   ident=copy.deepcopy(m["common_binding"]["identity"]);ident["artifacts"].pop(target);ident["semantic_dependencies"]=[e for e in ident["semantic_dependencies"] if e["target"]!=target];bad=reseal(m,ident);require(bad["common_binding"]["canonical_sha256"]!=COMMON_SHA,"MISSING_DEP_DIGEST");r["missing_"+target]=expect_failure("missing_"+target,lambda b=bad:validate_manifest(b,False))
   ident=copy.deepcopy(m["common_binding"]["identity"]);ident["artifacts"][target]["sha256"]="0"*64
   for e in ident["semantic_dependencies"]:
    if e["target"]==target:e["target_sha256"]="0"*64
   bad=reseal(m,ident);require(bad["common_binding"]["canonical_sha256"]!=COMMON_SHA,"SUB_DEP_DIGEST");r["substituted_"+target]=expect_failure("sub_"+target,lambda b=bad:validate_manifest(b,False))
  ident=copy.deepcopy(m["common_binding"]["identity"]);ident["semantic_dependencies"]=ident["semantic_dependencies"][:-1];bad=reseal(m,ident);r["missing_dependency_edge"]=expect_failure("edge",lambda:validate_manifest(bad,False))
  arts={k:strict_loads((ROOT/v["path"]).read_bytes()) for k,v in EXPECTED.items()};arts["entry_packet"]["unexpected_sha256"]="f"*64;r["uncovered_recursive_hash"]=expect_failure("uncovered",lambda:audit_semantic_closure(m["common_binding"]["identity"],arts))
  ref=copy.deepcopy(m["common_binding"]["identity"]["artifacts"]["payload"]);ref["path"]=lrel;ref["normalized_path"]=lrel;ref["mode"]="0600";ident=copy.deepcopy(m["common_binding"]["identity"]);ident["artifacts"]["payload"]=ref;bad=reseal(m,ident);r["path_digest_reseal"]=expect_failure("path_reseal",lambda:validate_manifest(bad,False))
 finally:shutil.rmtree(tmp)
 return r
def main():
 m=strict_load(MANIFEST);positive=validate_manifest(m);adversaries=run_adversaries(m);out={"version":"r6-data-quality-exact-input-verification-v3","status":"PASS_OWNER_BOUND_TRANSITIVE_PROVIDER_FREE_NONCOUNTABLE","strict_json_and_schema":"PASS","positive_checks":positive,"adversarial_checks":adversaries,"adversarial_passed":sum(x=="PASS_DENIED" for x in adversaries.values()),"adversarial_total":len(adversaries),"effects":{"provider":False,"network":False,"account":False,"private_state":False,"email":False,"business":False,"host":False,"scheduler":False},"countable":False};print(json.dumps(out,sort_keys=True,separators=(",",":")));return 0
if __name__=="__main__":sys.exit(main())
