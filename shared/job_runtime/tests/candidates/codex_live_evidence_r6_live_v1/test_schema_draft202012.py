import json,tempfile,unittest
from pathlib import Path
from _loader import module
from _support import NOW,REQUEST,gateway_factory,make,public_projection
try:from jsonschema import Draft202012Validator
except ImportError:Draft202012Validator=None
@unittest.skipUnless(Draft202012Validator is not None,"Draft202012 unavailable")
class T(unittest.TestCase):
 def test_representative_instance_for_every_schema(self):
  root=Path(__file__).resolve().parents[3]/"candidates"/"codex_live_evidence_r6_live_v1"/"schemas";schemas={p.name:json.loads(p.read_text()) for p in root.glob("*.schema.json")};self.assertEqual(len(schemas),10)
  for value in schemas.values():Draft202012Validator.check_schema(value)
  with tempfile.TemporaryDirectory() as d:
   grant,auth=make(d);lease=module("preflight").prepare(grant,auth,NOW,Path(d).resolve());process=module("process").FakeProcess();pr=process.start(grant["identity"]);gateway=module("gateway").FakeGateway(lease.store);gr=gateway.admit(REQUEST,grant["identity"],lease.operation_key,pr);tr=module("translator").translate(process.invoke(REQUEST));cr=module("cleanup").cleanup(process,True);lease.close()
   unknown={"schema_version":"codex-live-evidence-r6-live-evidence-v1","terminal_outcome":"UNKNOWN","reason_code":"R6_UNKNOWN","countable_observation":False,"catalog_preflight_count":1,"admission_count":1,"upstream_attempt_count":1,"inference_invocation_count":1,"cleanup_complete":True,"retry":False,"replay":False,"provider_status_calls":0,"reconciliation_dispatch":False,"durable_owner_private_evidence":True,"cleanup_receipt":cr,"unknown_evidence_path":str(Path(d)/"unknown.json")};rr=module("reconciliation").persist_unknown(Path(d)/"unknown.json",unknown)
   passed={"schema_version":"codex-live-evidence-r6-live-evidence-v1","terminal_outcome":"PASS","reason_code":"R6_PASS","countable_observation":False,"catalog_preflight_count":1,"admission_count":1,"upstream_attempt_count":1,"inference_invocation_count":1,"cleanup_complete":True,"process_receipt":pr,"gateway_receipt":gr,"translator_receipt":tr,"cleanup_receipt":cr}
   instances={"live-grant-template-v1.schema.json":module("grant").stage_a_template(),"live-grant-seal-v1.schema.json":grant,"live-preflight-receipt-v1.schema.json":lease.receipt,"live-process-receipt-v1.schema.json":pr,"live-gateway-receipt-v1.schema.json":gr,"live-translator-receipt-v1.schema.json":tr,"live-reconciliation-receipt-v1.schema.json":rr,"live-cleanup-receipt-v1.schema.json":cr,"live-evidence-v1.schema.json":passed,"sanitized-publication-v1.schema.json":public_projection()}
   self.assertEqual(set(instances),set(schemas))
   for name,value in instances.items():Draft202012Validator(schemas[name]).validate(value)
 def test_all_schemas_reject_nested_extras(self):
  root=Path(__file__).resolve().parents[3]/"candidates"/"codex_live_evidence_r6_live_v1"/"schemas";schema=json.loads((root/"live-grant-seal-v1.schema.json").read_text())
  with tempfile.TemporaryDirectory() as d:
   grant,_=make(d);grant["account"]["extra"]=1
   with self.assertRaises(Exception):Draft202012Validator(schema).validate(grant)
