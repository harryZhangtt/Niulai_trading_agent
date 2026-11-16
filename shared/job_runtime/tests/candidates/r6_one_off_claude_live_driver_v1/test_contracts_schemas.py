from __future__ import annotations
import copy,json,tempfile,unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1 import run_provider_free
from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1.claude_cli import synthetic_held_manifest
from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1.contracts import ContractError,validate_held_manifest
ROOT=Path(__file__).resolve().parents[5];SCHEMAS=ROOT/"shared/job_runtime/candidates/r6_one_off_claude_live_driver_v1/schemas";FIX=ROOT/"shared/job_runtime/tests/fixtures/r6_one_off_claude_live_driver_v1"
class ContractTests(unittest.TestCase):
 def test_manifest_contract_adversaries(self):
  value=synthetic_held_manifest();validate_held_manifest(value)
  for mutate in (lambda x:x.update(extra=1),lambda x:x.update(model="wrong"),lambda x:x["argv"].update(no_symlink=False),lambda x:x.update(digest="0"*64)):
   bad=copy.deepcopy(value);mutate(bad)
   with self.assertRaises(ContractError):validate_held_manifest(bad)
 def test_all_schemas_closed_recursively(self):
  def walk(x):
   if isinstance(x,dict):
    if x.get("type")=="object":self.assertIs(x.get("additionalProperties"),False)
    for v in x.values():walk(v)
   elif isinstance(x,list):
    for v in x:walk(v)
  for p in SCHEMAS.glob("*.json"):walk(json.loads(p.read_text()))
 def test_draft_all_scenarios_and_nested_adversaries(self):
  try:from jsonschema import Draft202012Validator
  except ImportError:self.skipTest("Draft202012 unavailable")
  schemas={p.name:json.loads(p.read_text()) for p in SCHEMAS.glob("*.json")}
  for s in schemas.values():Draft202012Validator.check_schema(s)
  validator=Draft202012Validator(schemas["driver-evidence-v1.schema.json"])
  cases=json.loads((FIX/"cases.json").read_text())
  for i,case in enumerate(cases):
   with tempfile.TemporaryDirectory(dir=FIX) as t:
    e=run_provider_free(Path(t)/("case"+str(i)),case).evidence;validator.validate(e)
    for mutate in (lambda x:x["limits"].update(extra=1),lambda x:x["publication"].update(extra=1),lambda x:x["unknown_fence"].update(extra=1),lambda x:x["effects"].update(extra=0)):
     bad=copy.deepcopy(e);mutate(bad);self.assertFalse(validator.is_valid(bad))
    if e["engine_readback"] is not None:
     bad=copy.deepcopy(e);bad["engine_readback"]["native_prompt"]["extra"]=1;self.assertFalse(validator.is_valid(bad))
    if e["process"] is not None:
     bad=copy.deepcopy(e);bad["process"]["nested_error"]["extra"]=1;self.assertFalse(validator.is_valid(bad))
    if e["ferry"] is not None:
     bad=copy.deepcopy(e);bad["ferry"]["upstream_count"]=2;self.assertFalse(validator.is_valid(bad))
