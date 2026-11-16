import ast,json,tempfile,unittest
from pathlib import Path
from _loader import module
class T(unittest.TestCase):
 def test_strict_contracts_authority_and_inert_imports(self):
  c=module("contracts")
  for raw in (b'{"a":1,"a":2}',b'{"a":NaN}'):
   with self.assertRaises(c.ContractError):c.strict_json_bytes(raw)
  c.enforce_authority("request_local_gateway",{"request admission"})
  root=Path(__file__).resolve().parents[3]/"candidates"/"codex_live_evidence_r6_live_v1";seen=set()
  for p in root.glob("*.py"):
   for n in ast.walk(ast.parse(p.read_text())):
    if isinstance(n,ast.Import):seen.update(x.name.split(".")[0] for x in n.names)
    elif isinstance(n,ast.ImportFrom) and n.module:seen.add(n.module.split(".")[0])
  self.assertFalse(seen&{"subprocess","socket","requests","urllib","openai","anthropic"});self.assertEqual(len(list((root/"schemas").glob("*.schema.json"))),10)
 def test_recursive_secret_values(self):
  c=module("contracts")
  for value in ({"nested":[{"value":"Bearer abcdef"}]},{"x":"password=hunter"},{"x":b"api_key=synthetic"}):
   with self.assertRaises(c.ContractError):c.scan_forbidden(value)
 def test_frozen_successor_closure_and_superseded_producer(self):
  import hashlib
  w=Path(__file__).resolve().parents[5];arch=w/"tuning/architecture/codex_live_evidence_r6_live_v1";closure=json.loads((arch/"source-closure-v1.json").read_text())
  self.assertEqual(closure["materialized_nonself_count"],len(closure["files"]))
  for item in closure["files"]:
   data=(w/item["path"]).read_bytes();self.assertEqual((len(data),hashlib.sha256(data).hexdigest()),(item["bytes"],item["sha256"]))
  pred=json.loads((arch/"predecessor-bindings-v1.json").read_text());item=pred["open_superseded_producer_verification"];data=(w/item["path"]).read_bytes();self.assertEqual((item["status"],len(data),hashlib.sha256(data).hexdigest()),("OPEN_SUPERSEDED_BY_SECURITY_REVIEW_FINDINGS",item["bytes"],item["sha256"]))
