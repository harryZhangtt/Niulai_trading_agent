"""Draft 2020-12 verifier for the provider-free Codex catalog candidate."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError
ROOT=Path(__file__).resolve().parents[3]
SCHEMAS=ROOT/'shared/job_runtime/candidates/r6_one_off_codex_catalog_v1/schemas'
def main():
 schemas={p.stem:json.loads(p.read_text()) for p in sorted(SCHEMAS.glob('*.json'))}
 for schema in schemas.values():Draft202012Validator.check_schema(schema)
 output={"command":"debug models","source":"provider","models":[{"slug":"gpt-6.1-sol","model":"gpt-6.1-sol","provider":"openai","origin":"provider","bundled":False}]}
 validator=Draft202012Validator(schemas['catalog-output-v1.schema']);validator.validate(output)
 rejected=0
 for bad in ({**output,"extra":1},{**output,"models":[]},{**output,"source":"bundled"}):
  try:validator.validate(bad)
  except ValidationError:rejected+=1
  else:raise SystemExit('invalid instance accepted')
 result={"draft":"2020-12","schemas":len(schemas),"valid_instances":1,"invalid_rejected":rejected,"result":"PASS"}
 encoded=json.dumps(result,sort_keys=True,separators=(',',':')).encode();print(encoded.decode());print(hashlib.sha256(encoded).hexdigest())
if __name__=='__main__':main()
