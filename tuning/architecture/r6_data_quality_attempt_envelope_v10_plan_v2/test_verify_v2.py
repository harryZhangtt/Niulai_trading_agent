from __future__ import annotations
import copy,hashlib,json,os,subprocess,sys,unittest
from pathlib import Path
sys.dont_write_bytecode=True;HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));import verify_v2 as v
class Tests(unittest.TestCase):
 def base(self):return copy.deepcopy(v.artifacts())
 def denied(self,code,fn):
  a=self.base();fn(a)
  with self.assertRaisesRegex(v.VerificationError,code):v.verify_structure(a)
 def test_structure_pending(self):self.assertEqual(len(v.verify_structure()[1]),12)
 def test_normal_fail_no_writes(self):
  before={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in HERE.iterdir() if x.is_file()};e=dict(os.environ);e["PYTHONDONTWRITEBYTECODE"]="1";r=subprocess.run([sys.executable,str(HERE/"verify_v2.py")],cwd=HERE,env=e,text=True,capture_output=True);self.assertEqual(r.returncode,2);self.assertEqual(json.loads(r.stdout)["status"],"FAIL_UNRESOLVED_PINS");self.assertEqual(before,{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in HERE.iterdir() if x.is_file()})
 def test_structure_only_no_promotion(self):
  r=subprocess.run([sys.executable,str(HERE/"verify_v2.py"),"--structure-only"],text=True,capture_output=True);self.assertEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout)["status"],"STRUCTURE_VALID_DESIGN_ONLY_NO_PROMOTION")
 def test_false_clean(self):
  self.denied("STATUS_ENUM:architecture",lambda a:a["architecture"].__setitem__("status","CLEAN"));self.denied("STATUS_ENUM:decision",lambda a:a["decision"].__setitem__("status","CLEAN"))
 def test_omitted_consumer(self):self.denied("CONSUMER_SET_EQUALITY:runner_v3",lambda a:a["graph"]["consumer_sets"]["runner_v3"].pop())
 def test_stale_successor(self):self.denied("STALE_SUCCESSOR_NAMESPACE",lambda a:a["manifest"]["snapshot"].pop())
 def test_provider_drift(self):
  for f in ("adapter_type","publication_driver","publication_driver_identity_sha256","research_material_profile_sha256"):
   with self.subTest(f=f):self.denied("PROVIDER_FIELDS:schemas",lambda a,k=f:a["schemas"]["exact_provider_bindings"]["ARM-A"].__setitem__(k,"DRIFT"))
 def test_bundle_projection_omission(self):self.denied("PROJECTIONS:schemas",lambda a:a["schemas"]["required_schema_projections"].pop())
 def test_graph_member_drift(self):self.denied("GRAPH_AGGREGATE",lambda a:a["graph"]["nodes"][0].__setitem__("sha256","0"*64))
 def test_anchors(self):
  r=self.base()["graph"]["review_anchors"];self.assertEqual(r["v1_plan_open"]["verdict"],"OPEN");self.assertEqual(r["execution_window_v2_open"]["findings"],["EW-V2-OPEN-004-001"]);self.assertEqual(r["metadata_preflight_v1_open"]["verdict"],"OPEN");self.assertEqual(r["codex_v6_clean"]["verdict"],"CLEAN_CODEX_LIVE_BOUNDARY_V6_PENDING_P0_V10");self.assertEqual(r["blind_map_v6_open"]["findings"],["OPEN-V6-01","OPEN-V6-02","OPEN-V6-03","OPEN-V6-04"]);self.assertEqual(r["runner_v3_open"]["verdict"],"OPEN");self.assertEqual(r["runner_v3_open"]["findings"],["OPEN-RUNNER-V3-PACKAGE-REACHABLE-KEY-AUTHORITY-001","OPEN-RUNNER-V3-PACKAGE-REACHABLE-LIVENESS-AUTHORITY-002","OPEN-P0-V9-G3-SCHEMA-002"]);self.assertEqual(r["runner_v4_clean_bound_legacy"]["verdict"],"CLEAN_PROVIDER_FREE_2X2_RUNNER_V4");self.assertEqual(r["claude_v9_clean"]["verdict"],"CLEAN_CLAUDE_LIVE_BOUNDARY_V9_EVIDENCE_RESEAL_PENDING_P0_V10")
if __name__=="__main__":unittest.main()
