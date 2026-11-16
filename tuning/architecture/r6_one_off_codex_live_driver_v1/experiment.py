"""Closure and optional concrete Draft 2020-12 verifier for the provider-free v3 successor."""
from __future__ import annotations
import hashlib,importlib.metadata,json,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT));CLOSURE=Path(__file__).with_name('source-closure-v1.json')
def verify():
 value=json.loads(CLOSURE.read_text());assert value['status']=='FROZEN_PROVIDER_FREE_STRENGTHENED_V3'
 for item in value['files']:
  raw=(ROOT/item['path']).read_bytes();assert len(raw)==item['bytes'];assert hashlib.sha256(raw).hexdigest()==item['sha256']
 assert not any(value['live_effects'].values());return {'status':'PASS','files':len(value['files']),'fixture_effects':value['fixture_effects'],'live_effects':value['live_effects']}
def verify_draft():
 from jsonschema import Draft202012Validator
 from shared.job_runtime.tests.candidates.r6_one_off_codex_live_driver_v1._support import FIXTURES,config,deps,held,preflight,prompt
 from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.driver import execute_provider_free
 schemas={p.name:json.loads(p.read_text()) for p in (ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_driver_v1/schemas').glob('*.json')}
 for schema in schemas.values():Draft202012Validator.check_schema(schema)
 with tempfile.TemporaryDirectory(dir=FIXTURES) as td:
  parent=Path(td);result=execute_provider_free(config(),preflight(),held(config()),prompt(),b'{}',ROOT,parent,'closure-draft-v3',deps(parent),datetime(2026,11,10,0,1,tzinfo=timezone.utc));assert result.outcome=='PASS'
  payload=json.loads(next(parent.glob('stage-b-execution-v3.json.payload')).read_text());instances={'driver-config-v1.schema.json':config(),'process-receipt-v1.schema.json':result.receipts['process'],'gateway-observer-receipt-v1.schema.json':result.receipts['gateway'],'terminal-translation-v1.schema.json':result.receipts['terminal'],'stage-b-execution-v1.schema.json':payload}
  for name,value in instances.items():Draft202012Validator(schemas[name]).validate(value)
 closure_raw=CLOSURE.read_bytes();self_raw=Path(__file__).read_bytes();return {'version':'r6-driver-v3-draft-verification-1','status':'PASS','python':sys.version.split()[0],'interpreter':sys.executable,'jsonschema':importlib.metadata.version('jsonschema'),'schemas':5,'instances':5,'fixture_outcome':'PASS','verifier_sha256':hashlib.sha256(self_raw).hexdigest(),'source_closure_sha256':hashlib.sha256(closure_raw).hexdigest()}
if __name__=='__main__':
 value=verify_draft() if '--draft' in sys.argv[1:] else verify();print(json.dumps(value,sort_keys=True,separators=(',',':')))
