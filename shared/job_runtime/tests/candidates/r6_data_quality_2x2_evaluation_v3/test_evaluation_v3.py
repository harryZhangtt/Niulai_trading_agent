from __future__ import annotations
import copy,hashlib,inspect,json,os,tempfile,unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3.harness import *
try:from jsonschema import Draft202012Validator
except ImportError:Draft202012Validator=None
def item(p,n,s="CORRECT"):return [{"id":"%s-%02d"%(p,i),"state":s} for i in range(n)]
def scalar(v=1,s="VALUE"):return {"state":s,"value":v if s=="VALUE" else None}
def evidence(alias,unknown=None,zero=False,facts=None):
 unknown=unknown or set();fresh=item("fresh",6);acc=[] if zero else item("claim",2)
 if "freshness" in unknown:fresh[0]["state"]="UNKNOWN"
 if "accuracy" in unknown:acc=[{"id":"claim-00","state":"UNKNOWN"}]
 return {"version":3,"blind_alias":alias,"retained":True,"freshness_items":fresh,"richness_items":item("meta",60),"depth_items":item("depth",6),"accuracy_claims":acc,"citation_items":item("cite",6),"source_coverage_items":item("cover",6),"incremental_facts":facts if facts is not None else [{"id":"base","role":"FACT","state":"CORRECT"}],"provider_cost_usd":scalar(.005),"metered_tool_cost_usd":scalar(.001),"elapsed_ms":scalar(1000),"provider_time_ms":scalar(700),"tool_time_ms":scalar(200)}
def gate(alias,fail=None):return {"version":3,"blind_alias":alias,"hard_gates":{x:("FAIL" if x==fail else"PASS") for x in HARD_GATES}}
def artifact(kind,alias):
 if kind=="sanitized_output":return {"version":3,"blind_alias":alias,"text":"sanitized"}
 if kind=="source_inventory":return {"version":3,"blind_alias":alias,"sources":[{"id":"s","url":"https://example.invalid","cutoff_ok":True}]}
 if kind=="citation_inventory":return {"version":3,"blind_alias":alias,"citations":[{"id":"c","source_id":"s","claim_id":"claim-00"}]}
 if kind=="raw_custody_receipt":return {"version":3,"blind_alias":alias,"raw_sha256":"d"*64,"owner_private":True}
 raise AssertionError(kind)
class Root:
 def __init__(self):self.t=tempfile.TemporaryDirectory();self.path=Path(self.t.name).resolve();os.chmod(self.path,0o700);self.store=ArtifactStore(self.path);self.n=0
 def close(self):self.t.cleanup()
 def write(self,kind,value,path=None,t=100):
  self.n+=1;rel=path or "b%02d/a%03d.json"%(int(value.get("blind_alias","BLIND-01").split("-")[-1]) if "blind_alias" in value else 0,self.n);p=self.path/rel;p.parent.mkdir(parents=True,exist_ok=True);os.chmod(p.parent,0o700);raw=json.dumps(value,sort_keys=True,separators=(",",":")).encode();p.write_bytes(raw);os.chmod(p,0o600);return {"kind":kind,"path":rel,"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"canonical_content_sha256":sha256_json(value),"immutable_at_ms":t}
 def bundle(self,alias,ev=None,fail=None):
  vals={"sanitized_output":artifact("sanitized_output",alias),"evidence_record":ev or evidence(alias),"source_inventory":artifact("source_inventory",alias),"citation_inventory":artifact("citation_inventory",alias),"deterministic_gate_report":gate(alias,fail),"raw_custody_receipt":artifact("raw_custody_receipt",alias)};return [self.write(k,vals[k]) for k in REF_KINDS]
 def mapref(self,mapping,nonce,t=50):return self.write("blind_map_commitment",{"version":3,"block_id":"fixture-block","commitment_sha256":sha256_json({"mapping":mapping,"nonce":nonce}),"committed_at_ms":t,"pre_call":True},t=t)
 def authority(self,relabel=False,bad_signature=False):
  reg={"version":3,"registry_id":"fixture-registry-v3","registry_kind":"LIVE" if relabel else"FIXTURE","countable":True if relabel else False,"graders":[{"grader_id":"fixture-g1","role":"G1"},{"grader_id":"fixture-g2","role":"G2"},{"grader_id":"fixture-g3","role":"G3"}]};rr=self.write("grader_registry",reg);rv={"version":3,"subject_content_sha256":rr["canonical_content_sha256"],"reviewer_id":"fixture-independent-reviewer","status":"CLEAN","signature":binding_signature("R6DQ_GRADER_REGISTRY_REVIEW_V3",rr["canonical_content_sha256"],"fixture-independent-reviewer")};rrv=self.write("grader_registry_review",rv)
  pairs={}
  for role,gid in (("G1","fixture-g1"),("G2","fixture-g2"),("G3","fixture-g3")):
   grant={"version":3,"registry_id":reg["registry_id"],"grader_id":gid,"role":role,"blind":True,"countable":reg["countable"],"valid_from_ms":1,"valid_through_ms":10000};gr=self.write("grader_grant",grant);sig=binding_signature("R6DQ_GRADER_GRANT_REVIEW_V3",gr["canonical_content_sha256"],"fixture-independent-reviewer");gv={"version":3,"subject_content_sha256":gr["canonical_content_sha256"],"reviewer_id":"fixture-independent-reviewer","status":"CLEAN","signature":"0"*64 if bad_signature and role=="G1" else sig};grv=self.write("grader_grant_review",gv);pairs[role]=(gr,grv)
  return GraderAuthority(self.store,rr,rrv,pairs,fixture=not relabel)
def grade(role,p,auth,t=300,dim=None,gates=None,grade_id=None,human=None):
 ds=[{"dimension":x,"level":"L3_STRONG"} for x in DIMENSIONS];gm=[{"gate":x,"disposition":"PASS"} for x in HARD_GATES];cm=[{"subject":x,"text":"fixture evidence"} for x in DIMENSIONS+("hard_gates",)]
 for k,v in (dim or {}).items():next(x for x in ds if x["dimension"]==k)["level"]=v
 for k,v in (gates or {}).items():next(x for x in gm if x["gate"]==k)["disposition"]=v
 gid=auth.grants[role]["grant"]["grader_id"] if human is None else human
 return seal_grade({"version":3,"grade_id":grade_id if grade_id is not None else p["blind_alias"]+"/"+role,"cell_blind_alias":p["blind_alias"],"packet_sha256":p["artifact_sha256"],"packet_refs_sha256":p["refs_sha256"],"grader_role":role,"human_reviewer_id":gid,"grader_grant_content_sha256":auth.grants[role]["grant_ref"]["canonical_content_sha256"],"blind":True,"dimensions":ds,"hard_gates":gm,"evidence_refs":[x["canonical_content_sha256"] for x in p["refs"]],"comments":cm,"independence_attestation":{"no_contact_with_other_graders":True,"no_provider_identity_access":True,"no_mapping_access":True,"no_conflict_of_interest":True,"attested_at_ms":t-1},"packet_committed_at_ms":p["committed_at_ms"],"produced_at_ms":t})
class V3(unittest.TestCase):
 def setUp(self):
  self.r=Root();self.addCleanup(self.r.close);self.mapping={ALIASES[c]:{"cell_id":c,"provider":CELL_MAP[c][0],"addon":CELL_MAP[c][1]} for c in CELL_ORDER};self.nonce="fixture-nonce";self.mapref=self.r.mapref(self.mapping,self.nonce);self.auth=self.r.authority()
 def packet(self,c,refs=None,ev=None,pre=60):return build_blind_packet(self.r.store,ALIASES[c],refs or self.r.bundle(ALIASES[c],ev),self.mapref,200,pre)
 def test_preflight_and_signature_surface(self):
  x=preflight_readiness({"version":3,"activation":False,"provider_calls_permitted":False,"root":str(self.r.path),"atomic_create":True,"no_replace":True,"artifact_kinds":list(ALL_ARTIFACT_KINDS)+["blind_packet","grade","metric","unblind"]});self.assertEqual(len(x["schemas"]),14);self.assertEqual(set(inspect.signature(authorize_unblinding).parameters),{"store","packets","grades","authority","mapping","nonce","opened_at_ms"})
 def test_exact_six_unique_ordered_refs(self):
  refs=self.r.bundle("BLIND-01")
  for bad in (refs[:-1],refs+[refs[-1]],[refs[1],refs[0],*refs[2:]]):
   with self.assertRaises(ContractError):build_blind_packet(self.r.store,"BLIND-01",bad,self.mapref,200,60)
  p=self.packet(CELL_ORDER[0]);body={k:v for k,v in p.items() if k not in ("artifact_sha256","artifact_bytes","immutable")};body["refs_sha256"]="0"*64;bad=seal({**body,"immutable":True})
  with self.assertRaisesRegex(ContractError,"PACKET_REFS_DIGEST"):validate_packet_runtime(self.r.store,bad)
 def test_lexical_paths_and_all_treatment_tokens(self):
  base=self.r.write("sanitized_output",artifact("sanitized_output","BLIND-01"))
  bad=["",".","./a.json","a/./b.json","a//b.json","../a.json","/a.json","a\\b.json"]+["x-%s.json"%x for x in ("provider","model","addon","dq","layer","order","cost","latency","claude","codex","opus","gpt","on","off","baseline","treatment","sol")]
  for path in bad:
   with self.subTest(path=path),self.assertRaises(ContractError):self.r.store.read({**base,"path":path})
  ok=self.r.write("sanitized_output",artifact("sanitized_output","BLIND-01"),path="console.json");self.r.store.read(ok)
 def test_nofollow_mode_hash_and_canonical(self):
  ref=self.r.write("sanitized_output",artifact("sanitized_output","BLIND-01"));path=self.r.path/ref["path"]
  for key,value in (("bytes",999),("sha256","0"*64),("canonical_content_sha256","0"*64)):
   with self.subTest(key=key),self.assertRaises(ContractError):self.r.store.read({**ref,key:value})
  target=self.r.path/"neutral-target.json";path.rename(target);path.symlink_to(target)
  with self.assertRaisesRegex(ContractError,"REF_OPEN_NOFOLLOW"):self.r.store.read(ref)
 def test_grade_empty_ids_and_order_drift(self):
  p=self.packet(CELL_ORDER[0])
  for g,code in ((grade("G1",p,self.auth,grade_id=""),"GRADE_ID"),(grade("G1",p,self.auth,human=""),"GRADE_ROLE")):
   with self.subTest(code=code),self.assertRaisesRegex(ContractError,code):validate_grade(g,p,self.auth)
  for field in ("dimensions","hard_gates","comments"):
   g=grade("G1",p,self.auth);body={k:v for k,v in g.items() if k not in ("artifact_sha256","artifact_bytes","immutable")};body[field][0],body[field][1]=body[field][1],body[field][0];bad=seal_grade(body)
   with self.subTest(field=field),self.assertRaises(ContractError):validate_grade(bad,p,self.auth)
 def test_registry_grant_authority_and_relabel(self):
  p=self.packet(CELL_ORDER[0]);g=grade("G1",p,self.auth,human="self-declared")
  with self.assertRaisesRegex(ContractError,"GRADE_EXTERNAL_GRANT_BINDING"):validate_grade(g,p,self.auth)
  with self.assertRaisesRegex(ContractError,"LIVE_REGISTRY_NOT_EXTERNALLY_PINNED"):self.r.authority(relabel=True)
  with self.assertRaisesRegex(ContractError,"AUTH_REVIEW_SIGNATURE"):self.r.authority(bad_signature=True)
 def test_role_id_collision_preserved(self):
  facts=[{"id":"same","role":"FACT","state":"CORRECT"},{"id":"same","role":"CONFLICT","state":"CORRECT"}];off=evidence("BLIND-01",facts=[]);on=evidence("BLIND-03",facts=facts);m=derive_cell(on,CELL_ORDER[2],off)["metrics"]["incremental_information_value"];self.assertEqual((m["numerator"],m["denominator"]),(2,2))
  dup=facts+[dict(facts[0])]
  with self.assertRaisesRegex(ContractError,"FACT_DUPLICATE"):validate_evidence(evidence("BLIND-03",facts=dup),"BLIND-03")
 def test_map_commitment_precall_opening_and_ref_drift(self):
  with self.assertRaisesRegex(ContractError,"PACKET_MAP_NOT_PRECALL"):self.packet(CELL_ORDER[0],pre=40)
  packets={c:self.packet(c) for c in CELL_ORDER};grades={c:[grade("G1",packets[c],self.auth,300+i*2),grade("G2",packets[c],self.auth,301+i*2)] for i,c in enumerate(CELL_ORDER)}
  with self.assertRaisesRegex(ContractError,"UNBLIND_COMMITMENT_OPENING"):authorize_unblinding(self.r.store,packets,grades,self.auth,self.mapping,"wrong",1000)
  drift=copy.deepcopy(packets);other=self.r.mapref(self.mapping,"other",t=50);body={k:v for k,v in drift[CELL_ORDER[1]].items() if k not in ("artifact_sha256","artifact_bytes")};body["blind_map_commitment_ref"]=other;body["blind_map_commitment_content_sha256"]=other["canonical_content_sha256"];drift[CELL_ORDER[1]]=seal(body)
  with self.assertRaisesRegex(ContractError,"UNBLIND_COMMITMENT_REF_DRIFT"):authorize_unblinding(self.r.store,drift,grades,self.auth,self.mapping,self.nonce,1000)
 def test_substituted_evidence_and_gate(self):
  for kind,new in (("evidence_record",evidence("BLIND-01",zero=True)),("deterministic_gate_report",gate("BLIND-01","reference_parseability"))):
   p=self.packet(CELL_ORDER[0]);ref=next(x for x in p["refs"] if x["kind"]==kind);path=self.r.path/ref["path"];path.write_text(json.dumps(new));os.chmod(path,0o600)
   with self.subTest(kind=kind),self.assertRaises(ContractError):evaluate_cell(self.r.store,p,[grade("G1",p,self.auth),grade("G2",p,self.auth,301)],self.auth)
 def test_field_specific_and_cost(self):
  m=derive_cell(evidence("BLIND-01",unknown={"freshness"}),CELL_ORDER[0])["metrics"];self.assertEqual(m["freshness"]["status"],"UNKNOWN");self.assertEqual(m["accuracy"]["status"],"VALUE")
  u=derive_cell(evidence("BLIND-01",unknown={"accuracy"}),CELL_ORDER[0])["metrics"]["cost"];self.assertEqual((u["usd_per_correct_atomic_claim_status"],u["usd_per_correct_atomic_claim"]),("UNKNOWN",None));z=derive_cell(evidence("BLIND-01",zero=True),CELL_ORDER[0])["metrics"]["cost"];self.assertEqual((z["usd_per_correct_atomic_claim_status"],z["usd_per_correct_atomic_claim"]),("NOT_APPLICABLE",None))
 def test_valid_four_cell_fixture(self):
  packets={c:self.packet(c) for c in CELL_ORDER};grades={c:[grade("G1",packets[c],self.auth,300+i*2),grade("G2",packets[c],self.auth,301+i*2)] for i,c in enumerate(CELL_ORDER)};x=authorize_unblinding(self.r.store,packets,grades,self.auth,self.mapping,self.nonce,1000);self.assertEqual(x["status"],"FIXTURE_NOT_COUNTABLE");self.assertFalse(x["countable"])
 @unittest.skipIf(Draft202012Validator is None,"jsonschema unavailable")
 def test_fourteen_closed_schemas_and_nested_grade(self):
  root=Path(__file__).resolve().parents[3]/"candidates/r6_data_quality_2x2_evaluation_v3";ps=list(root.glob("*.schema.json"));self.assertEqual(len(ps),14)
  for p in ps:Draft202012Validator.check_schema(json.loads(p.read_text()))
  packet=self.packet(CELL_ORDER[0]);g=grade("G1",packet,self.auth);v=Draft202012Validator(json.loads((root/"grade-record-v3.schema.json").read_text()));v.validate(g)
  for branch in ("dimensions","hard_gates","comments"):
   bad=copy.deepcopy(g);bad[branch][0]["extra"]=True;self.assertTrue(list(v.iter_errors(bad)))
if __name__=="__main__":unittest.main()
