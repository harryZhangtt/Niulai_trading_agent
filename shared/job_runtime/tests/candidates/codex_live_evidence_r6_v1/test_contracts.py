import ast,json,tempfile,unittest
from pathlib import Path
from _loader import module
from _support import REQUEST,NOW,fixture,make
class ContractsTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.c=module("contracts");cls.pre=module("preflight");cls.root=Path(__file__).resolve().parents[3]/"candidates"/"codex_live_evidence_r6_v1"
 def test_six_closed_schemas_and_identity_ref(self):
  files=sorted((self.root/"schemas").glob("*.schema.json"));self.assertEqual(len(files),6)
  for path in files:
   schema=json.loads(path.read_text());self.assertIn("r6_identity_envelope",schema["$defs"]);self.assertFalse(schema["$defs"]["r6_identity_envelope"]["additionalProperties"]);self.assertTrue(schema.get("additionalProperties") is False or all(branch.get("additionalProperties") is False for branch in schema.get("oneOf",[])))
  live=json.loads((self.root/"schemas/live-evidence-v1.schema.json").read_text());self.assertEqual(len(live["oneOf"]),3);self.assertEqual({x["properties"]["terminal_outcome"]["const"] for x in live["oneOf"]},{"PASS","STOP","UNKNOWN"})
 def test_duplicate_and_nonfinite_rejected(self):
  with self.assertRaisesRegex(self.c.R6ContractError,"R6_DUPLICATE_KEY"):self.c.strict_json_bytes(b'{"a":1,"a":2}')
  with self.assertRaisesRegex(self.c.R6ContractError,"R6_NONFINITE"):self.c.strict_json_bytes(b'{"a":NaN}')
 def test_identity_exact_and_old_reuse_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   v=make(d)["identity"]
   for mutation in ({**v,"extra":"x"},{**v,"job_id":"claude-live-smoke-20261109T123642Z"},{**v,"slot_id":"66ca95b8a8cd1b6471b893a13169249d8a36713e5475665e42352a13dbec2186"}):
    with self.assertRaises(self.c.R6ContractError):self.c.validate_identity(mutation)
 def test_countable_false_and_outcome_exact(self):
  cases=[{"terminal_outcome":"PASS","countable_observation":False,"upstream_attempt_count":1,"terminal_complete":True,"cleanup_complete":True},{"terminal_outcome":"STOP","countable_observation":False,"upstream_attempt_count":0,"submission":"DEFINITELY_NOT_SUBMITTED"},{"terminal_outcome":"UNKNOWN","countable_observation":False,"upstream_attempt_count":1,"admission_count":1,"replay":False,"retry":False,"provider_status_calls":0,"reconciliation_dispatch":False,"durable_after_reconstruction":True}]
  for v in cases:self.c.validate_outcome(v)
  for v in cases:
   bad=dict(v);bad["countable_observation"]=True
   with self.assertRaises(self.c.R6ContractError):self.c.validate_outcome(bad)
 def test_recursive_secret_and_raw_rejection(self):
  for v in ({"nested":{"raw_stdout":"x"}},{"nested":[{"ok":"Bearer abcdefghijklmnop"}]},{"credentials":"x"}):
   with self.assertRaises(self.c.R6ContractError):self.c.scan_public(v)
 def test_inert_import_closure_and_forbidden_imports(self):
  forbidden={"socket","subprocess","requests","urllib","anthropic","openai"}
  imported=set()
  for p in list(self.root.glob("*.py"))+[Path(__file__).resolve().parents[5]/"tuning/architecture/codex_live_evidence_r6_v1/experiment.py"]:
   tree=ast.parse(p.read_text())
   for n in ast.walk(tree):
    if isinstance(n,ast.Import):imported.update(x.name.split('.')[0] for x in n.names)
    elif isinstance(n,ast.ImportFrom) and n.module:imported.add(n.module.split('.')[0])
  self.assertFalse(imported&forbidden)
 def test_secure_file_identity_and_path_substitution(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);bound=grant["artifacts"]["prompt"];self.assertEqual(self.c.secure_read(bound,Path(d)),b"synthetic prompt\n")
   Path(bound["path"]).unlink();Path(bound["path"]).write_bytes(b"replacement bytes\n")
   with self.assertRaises(self.c.R6ContractError):self.c.secure_read(bound,Path(d))
 def test_symlink_component_rejected(self):
  with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as other:
   root=Path(d);link=root/"link";link.symlink_to(other,target_is_directory=True);p=Path(other)/"x";p.write_bytes(b"x");bound={"path":str(link/"x"),"bytes":1,"sha256":self.c.sha256_bytes(b"x")}
   with self.assertRaises(self.c.R6ContractError):self.c.secure_read(bound,root)
 def test_catalog_selected_model_exactly_once(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);self.assertEqual(self.pre.run_preflight(grant,synthetic_root=Path(d),now=NOW)["decision"],"PASS")
   p=Path(grant["artifacts"]["model_catalog"]["path"]);p.chmod(0o600);p.write_bytes(b"model-test\nmodel-test\n");p.chmod(0o400);grant["artifacts"]["model_catalog"].update(bytes=p.stat().st_size,sha256=self.c.sha256_bytes(p.read_bytes()))
   self.assertEqual(self.pre.run_preflight(grant,synthetic_root=Path(d),now=NOW)["reason_code"],"R6_CATALOG_SELECTED_MODEL_NOT_EXACTLY_ONCE")
 def test_source_closure_and_predecessors_match_current_bytes(self):
  import hashlib
  workspace=Path(__file__).resolve().parents[5]
  architecture=workspace/"tuning/architecture/codex_live_evidence_r6_v1"
  closure=json.loads((architecture/"source-closure-v1.json").read_text());self.assertEqual(closure["materialized_nonself_count"],len(closure["files"]))
  for item in closure["files"]:
   data=(workspace/item["path"]).read_bytes();self.assertEqual((len(data),hashlib.sha256(data).hexdigest()),(item["bytes"],item["sha256"]))
  predecessor=json.loads((architecture/"predecessor-bindings-v1.json").read_text());self.assertTrue(predecessor["all_current_bindings_match"])
  for item in [predecessor["design"],predecessor["design_review"],*predecessor["frozen_predecessors"]]:
   data=(workspace/item["path"]).read_bytes();self.assertEqual((len(data),hashlib.sha256(data).hexdigest()),(item["bytes"],item["sha256"]))
