from __future__ import annotations
import copy, hashlib, json, os, tempfile, unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v2.harness import *
try:from jsonschema import Draft202012Validator
except ImportError:Draft202012Validator=None

def item(prefix,n,state="CORRECT"):return [{"id":"%s-%02d"%(prefix,i),"state":state} for i in range(n)]
def scalar(value=1,state="VALUE"):return {"state":state,"value":value if state=="VALUE" else None}
def evidence(alias,unknown=None,zero=False,mixed=False):
    unknown=unknown or set(); acc=[] if zero else item("claim",2)
    if "accuracy" in unknown:acc=[{"id":"claim-00","state":"UNKNOWN"}]
    fresh=item("fresh",6)
    if "freshness" in unknown:fresh[0]["state"]="UNKNOWN"
    if mixed:fresh[0]["state"]="WRONG";fresh[1]["state"]="MISSING"
    return {"version":2,"blind_alias":alias,"retained":True,"freshness_items":fresh,"richness_items":item("meta",60),"depth_items":item("depth",6),"accuracy_claims":acc,"citation_items":item("cite",6),"source_coverage_items":item("cover",6),"incremental_facts":[{"id":"base","role":"FACT","state":"CORRECT"}]+([{"id":"new","role":"FACT","state":"CORRECT"},{"id":"false-new","role":"FACT","state":"WRONG"}] if alias in ("BLIND-02","BLIND-03") else []),"provider_cost_usd":scalar(.005),"metered_tool_cost_usd":scalar(.001),"elapsed_ms":scalar(1000),"provider_time_ms":scalar(700),"tool_time_ms":scalar(200)}
def gates(alias,fail=None):return {"version":2,"blind_alias":alias,"hard_gates":{x:("FAIL" if x==fail else "PASS") for x in HARD_GATES}}
def other(kind,alias):
    if kind=="sanitized_output":return {"version":2,"blind_alias":alias,"text":"sanitized fixture"}
    if kind=="source_inventory":return {"version":2,"blind_alias":alias,"sources":[{"id":"s1","url":"https://example.invalid/source","cutoff_ok":True}]}
    if kind=="citation_inventory":return {"version":2,"blind_alias":alias,"citations":[{"id":"c1","source_id":"s1","claim_id":"claim-00"}]}
    if kind=="raw_custody_receipt":return {"version":2,"blind_alias":alias,"raw_sha256":"d"*64,"owner_private":True}
    raise AssertionError(kind)
class Root:
 def __init__(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name).resolve();os.chmod(self.path,0o700);self.store=ArtifactStore(self.path);self.counter=0
 def close(self):self.tmp.cleanup()
 def write(self,kind,value,path=None,t=100):
  self.counter+=1;rel=path or "b%02d/a%02d.json"%(int(value.get("blind_alias","BLIND-01").split("-")[-1]),self.counter);p=self.path/rel;p.parent.mkdir(parents=True,exist_ok=True);os.chmod(p.parent,0o700);data=json.dumps(value,sort_keys=True,separators=(",",":")).encode();p.write_bytes(data);os.chmod(p,0o600);return {"kind":kind,"path":rel,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data),"canonical_content_sha256":sha256_json(value),"immutable_at_ms":t}
 def bundle(self,alias,ev=None,fail=None):
  values={"sanitized_output":other("sanitized_output",alias),"evidence_record":ev or evidence(alias),"source_inventory":other("source_inventory",alias),"citation_inventory":other("citation_inventory",alias),"deterministic_gate_report":gates(alias,fail),"raw_custody_receipt":other("raw_custody_receipt",alias)}
  return [self.write(k,values[k]) for k in REF_KINDS]
def grade(role,p,user,t=300,levels=None,hg=None):
 d={x:"L3_STRONG" for x in DIMENSIONS};d.update(levels or {});g={x:"PASS" for x in HARD_GATES};g.update(hg or {});comments={x:"fixture evidence" for x in DIMENSIONS};comments["hard_gates"]="fixture gates";return seal_grade({"version":2,"grade_id":p["blind_alias"]+"/"+role,"cell_blind_alias":p["blind_alias"],"packet_sha256":p["artifact_sha256"],"packet_refs_sha256":p["refs_sha256"],"grader_role":role,"reviewer_kind":"FIXTURE_HUMAN","human_reviewer_id":user,"blind":True,"countable":False,"dimensions":d,"hard_gates":g,"evidence_refs":[x["canonical_content_sha256"] for x in p["refs"]],"comments":comments,"independence_attestation":{"no_contact_with_other_graders":True,"no_provider_identity_access":True,"no_mapping_access":True,"no_conflict_of_interest":True,"attested_at_ms":t-1},"packet_committed_at_ms":p["committed_at_ms"],"produced_at_ms":t})
class V2Tests(unittest.TestCase):
 def setUp(self):self.r=Root();self.addCleanup(self.r.close)
 def packet(self,cell,ev=None,fail=None):return build_blind_packet(self.r.store,ALIASES[cell],self.r.bundle(ALIASES[cell],ev,fail),200)
 def test_preflight(self):
  x=preflight_readiness({"version":2,"activation":False,"provider_calls_permitted":False,"root":str(self.r.path),"atomic_create":True,"no_replace":True,"artifact_kinds":list(REF_KINDS)+["blind_packet","grade","metric","unblind"]});self.assertEqual(len(x["schemas"]),10)
 def test_traversal_absolute_and_path_leakage(self):
  base=self.r.write("sanitized_output",other("sanitized_output","BLIND-01"))
  for path,code in (("../a.json","REF_TRAVERSAL"),("/tmp/a.json","REF_TRAVERSAL"),*(("b01/%s.json"%x,"REF_PATH_LEAKAGE") for x in ("provider","model","addon","order","cost","latency","claude","codex"))):
   q={**base,"path":path}
   with self.subTest(path=path),self.assertRaisesRegex(ContractError,code):self.r.store.read(q)
 def test_nofollow_and_mode(self):
  ref=self.r.write("sanitized_output",other("sanitized_output","BLIND-01"));p=self.r.path/ref["path"];target=self.r.path/"target.json";p.rename(target);p.symlink_to(target)
  with self.assertRaisesRegex(ContractError,"REF_OPEN_NOFOLLOW"):self.r.store.read(ref)
  p.unlink();target.rename(p);os.chmod(p,0o644)
  with self.assertRaisesRegex(ContractError,"REF_MODE"):self.r.store.read(ref)
  os.chmod(p,0o600);outside=self.r.path/"outside";outside.mkdir();os.chmod(outside,0o700);(outside/"x.json").write_bytes(p.read_bytes());os.chmod(outside/"x.json",0o600);link=self.r.path/"jump";link.symlink_to(outside,target_is_directory=True)
  q={**ref,"path":"jump/x.json"}
  with self.assertRaisesRegex(ContractError,"REF_OPEN_NOFOLLOW"):self.r.store.read(q)
 def test_hash_bytes_and_canonical(self):
  ref=self.r.write("sanitized_output",other("sanitized_output","BLIND-01"))
  for key,val,code in (("bytes",999,"REF_BYTES"),("sha256","0"*64,"REF_HASH"),("canonical_content_sha256","0"*64,"REF_CANONICAL_CONTENT")):
   with self.subTest(key=key),self.assertRaisesRegex(ContractError,code):self.r.store.read({**ref,key:val})
 def test_grade_binds_exact_packet_refs(self):
  p=self.packet(CELL_ORDER[0]);g=grade("G1",p,"g1");body={k:v for k,v in g.items() if k not in ("artifact_sha256","artifact_bytes","immutable")};body["evidence_refs"]=body["evidence_refs"][:-1]+["0"*64];bad=seal_grade(body)
  with self.assertRaisesRegex(ContractError,"GRADE_EXACT_PACKET_REFS"):validate_grade(bad,p,True)
 def test_substituted_evidence_rejected_at_unblind(self):
  p=self.packet(CELL_ORDER[0]);ref=next(x for x in p["refs"] if x["kind"]=="evidence_record");path=self.r.path/ref["path"];path.write_text(json.dumps(evidence("BLIND-01",zero=True)));os.chmod(path,0o600)
  with self.assertRaisesRegex(ContractError,"REF_(BYTES|HASH)"):evaluate_cell(self.r.store,p,[grade("G1",p,"g1"),grade("G2",p,"g2",301)],True)
 def test_substituted_gate_rejected_at_unblind(self):
  p=self.packet(CELL_ORDER[0]);ref=next(x for x in p["refs"] if x["kind"]=="deterministic_gate_report");path=self.r.path/ref["path"];path.write_text(json.dumps(gates("BLIND-01","reference_parseability")));os.chmod(path,0o600)
  with self.assertRaisesRegex(ContractError,"REF_(BYTES|HASH)"):evaluate_cell(self.r.store,p,[grade("G1",p,"g1"),grade("G2",p,"g2",301)],True)
 def test_root_substitution_rejected(self):
  p=self.packet(CELL_ORDER[0]);otherroot=Root();self.addCleanup(otherroot.close)
  with self.assertRaisesRegex(ContractError,"PACKET_ROOT_SUBSTITUTION"):evaluate_cell(otherroot.store,p,[grade("G1",p,"g1"),grade("G2",p,"g2",301)],True)
 def test_mixed_missing_wrong_are_distinct(self):
  m=derive_cell(evidence("BLIND-01",mixed=True),CELL_ORDER[0])["metrics"]["freshness"];self.assertEqual((m["wrong_count"],m["missing_count"],m["denominator"]),(1,1,6));self.assertEqual(m["status"],"VALUE")
 def test_selective_unknown_only_affects_freshness(self):
  m=derive_cell(evidence("BLIND-01",unknown={"freshness"}),CELL_ORDER[0])["metrics"];self.assertEqual(m["freshness"]["status"],"UNKNOWN");self.assertEqual(m["accuracy"]["status"],"VALUE");self.assertEqual(m["cost"]["status"],"VALUE")
 def test_cost_per_claim_unknown_and_na(self):
  u=derive_cell(evidence("BLIND-01",unknown={"accuracy"}),CELL_ORDER[0])["metrics"]["cost"];self.assertEqual(u["usd_per_correct_atomic_claim_status"],"UNKNOWN");self.assertIsNone(u["usd_per_correct_atomic_claim"])
  z=derive_cell(evidence("BLIND-01",zero=True),CELL_ORDER[0])["metrics"]["cost"];self.assertEqual(z["usd_per_correct_atomic_claim_status"],"NOT_APPLICABLE");self.assertIsNone(z["usd_per_correct_atomic_claim"])
 def test_nested_grade_extra_rejected_harness(self):
  p=self.packet(CELL_ORDER[0]);g=grade("G1",p,"g1");body={k:v for k,v in g.items() if k not in ("artifact_sha256","artifact_bytes","immutable")};body["independence_attestation"]["extra"]=True;bad=seal_grade(body)
  with self.assertRaisesRegex(ContractError,"GRADE_ATTEST_FIELDS"):validate_grade(bad,p,True)
 @unittest.skipIf(Draft202012Validator is None,"jsonschema unavailable")
 def test_all_schemas_closed_and_grade_nested_extras(self):
  root=Path(__file__).resolve().parents[3]/"candidates/r6_data_quality_2x2_evaluation_v2";schemas=list(root.glob("*.schema.json"));self.assertEqual(len(schemas),10)
  for path in schemas:Draft202012Validator.check_schema(json.loads(path.read_text()))
  p=self.packet(CELL_ORDER[0]);g=grade("G1",p,"g1");s=json.loads((root/"grade-record-v2.schema.json").read_text());v=Draft202012Validator(s);v.validate(g)
  for branch in ("dimensions","hard_gates","comments","independence_attestation"):
   bad=copy.deepcopy(g);bad[branch]["extra"]=True;self.assertTrue(list(v.iter_errors(bad)),branch)
 def test_g3_and_hard_gate_rules(self):
  p=self.packet(CELL_ORDER[0],fail="reference_parseability");g1=grade("G1",p,"g1",levels={"accuracy":"L0_UNUSABLE"});g2=grade("G2",p,"g2",301,levels={"accuracy":"L2_ADEQUATE"})
  with self.assertRaisesRegex(ContractError,"G3_REQUIREMENT"):evaluate_cell(self.r.store,p,[g1,g2],True)
  g3=grade("G3",p,"g3",302)
  with self.assertRaisesRegex(ContractError,"G3_HARD_GATE_OVERRIDE"):evaluate_cell(self.r.store,p,[g1,g2,g3],True)
 def test_valid_four_cell_and_early_unblind(self):
  packets={};grades={}
  for i,c in enumerate(CELL_ORDER):
   packets[c]=self.packet(c);grades[c]=[grade("G1",packets[c],"g1-"+c,300+i*2),grade("G2",packets[c],"g2-"+c,301+i*2)]
  mapping={ALIASES[c]:{"cell_id":c,"provider":CELL_MAP[c][0],"addon":CELL_MAP[c][1]} for c in CELL_ORDER};nonce="n";commit=sha256_json({"mapping":mapping,"nonce":nonce})
  with self.assertRaisesRegex(ContractError,"UNBLIND_EARLY"):authorize_unblinding(self.r.store,packets,grades,mapping,nonce,commit,302,True)
  x=authorize_unblinding(self.r.store,packets,grades,mapping,nonce,commit,1000,True);self.assertEqual(x["status"],"FIXTURE_NOT_COUNTABLE");self.assertFalse(x["countable"]);self.assertEqual(x["block_metric"]["contrasts"]["accuracy"]["interaction"]["status"],"VALUE")
 def test_live_rejects_fixture_human(self):
  p=self.packet(CELL_ORDER[0])
  with self.assertRaisesRegex(ContractError,"LIVE_FAKE_HUMAN_FORBIDDEN"):validate_grade(grade("G1",p,"g1"),p,False)
if __name__=="__main__":unittest.main()
