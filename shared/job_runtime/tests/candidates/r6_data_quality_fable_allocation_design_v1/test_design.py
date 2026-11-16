from __future__ import annotations
import ast,copy,hashlib,json,math,unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_fable_allocation_design_v1.design import DESIGN_SHA256,DesignError,canonical_bytes,default_design,strict_json_loads,validate_design
ROOT=Path(__file__).resolve().parents[5];FIX=ROOT/'shared/job_runtime/tests/fixtures/r6_data_quality_fable_allocation_design_v1/allocation-design-v1.json';VALUE=json.loads(FIX.read_text())
class DesignTests(unittest.TestCase):
 def reject(self,value):
  with self.assertRaises(DesignError):validate_design(value)
 def test_nominal_canonical_digest_and_default_deny(self):
  self.assertEqual(validate_design(copy.deepcopy(VALUE)),VALUE);self.assertEqual(hashlib.sha256(canonical_bytes(VALUE)).hexdigest(),DESIGN_SHA256);default=default_design();self.assertFalse(default['activation']);self.assertFalse(default['countable']);self.assertTrue(all(x==0 for x in default['effects'].values()))
 def test_exact_two_disabled_ordered_symmetric_jobs(self):
  jobs=VALUE['jobs'];self.assertEqual([(x['job_id'],x['cell_id'],x['enabled'],x['dq_enabled']) for x in jobs],[('fable-adapter-cell-0','F51DQ-6E3A9C17',False,False),('fable-adapter-cell-1','F51DQ-B4D208FE',False,True)]);a={k:v for k,v in jobs[0].items() if k not in ('job_id','cell_id','dq_enabled')};b={k:v for k,v in jobs[1].items() if k not in ('job_id','cell_id','dq_enabled')};self.assertEqual(a,b)
  x=copy.deepcopy(VALUE);x['jobs'].reverse();self.reject(x)
  x=copy.deepcopy(VALUE);x['jobs'][1]['resource_key']='other';self.reject(x)
 def test_every_root_extra_and_missing_key_reject(self):
  for key in VALUE:
   x=copy.deepcopy(VALUE);x.pop(key);self.reject(x)
  x=copy.deepcopy(VALUE);x['extra']=True;self.reject(x)
 def test_nested_extra_missing_and_cardinality_reject(self):
  targets=('prompt_artifact','execution','schedule_intent','output_custody','prerequisite','effects')
  for target in targets:
   key=next(iter(VALUE[target]));x=copy.deepcopy(VALUE);x[target].pop(key);self.reject(x);x=copy.deepcopy(VALUE);x[target]['extra']=0;self.reject(x)
  for index in range(2):
   key=next(iter(VALUE['jobs'][index]));x=copy.deepcopy(VALUE);x['jobs'][index].pop(key);self.reject(x);x=copy.deepcopy(VALUE);x['jobs'][index]['extra']=0;self.reject(x)
  for jobs in (VALUE['jobs'][:1],VALUE['jobs']+[copy.deepcopy(VALUE['jobs'][0])]):x=copy.deepcopy(VALUE);x['jobs']=copy.deepcopy(jobs);self.reject(x)
 def test_binding_treatment_limits_schedule_and_custody_drift_reject(self):
  mutations=[('model','claude-opus-5-5'),('provider','codex_cli'),('integration_closure_sha256','0'*64),('integration_sha256','0'*64),('bridge_closure_sha256','0'*64),('adapter_closure_sha256','0'*64),('logical_database_id','other')]
  for key,value in mutations:x=copy.deepcopy(VALUE);x[key]=value;self.reject(x)
  paths=[('prompt_artifact','sha256','0'*64),('execution','max_workers',2),('schedule_intent','window_seconds',301),('output_custody','no_replace',False),('prerequisite','engine_closed','ASSUMED'),('effects','provider',1)]
  for section,key,value in paths:x=copy.deepcopy(VALUE);x[section][key]=value;self.reject(x)
  for index,key,value in [(0,'enabled',True),(0,'dq_enabled',True),(1,'attempts',2),(1,'fallbacks',1)]:
   x=copy.deepcopy(VALUE)
   if key in x['jobs'][index]:x['jobs'][index][key]=value
   else:x['jobs'][index]['limits'][key]=value
   self.reject(x)
 def test_exact_types_reject_bool_int_float_and_container_aliases(self):
  variants=[]
  x=copy.deepcopy(VALUE);x['version']=True;variants.append(x)
  x=copy.deepcopy(VALUE);x['jobs'][0]['limits']['attempts']=True;variants.append(x)
  x=copy.deepcopy(VALUE);x['effects']['provider']=False;variants.append(x)
  x=copy.deepcopy(VALUE);x['execution']['max_workers']=1.0;variants.append(x)
  x=copy.deepcopy(VALUE);x['schedule_intent']['window_seconds']=300.0;variants.append(x)
  x=copy.deepcopy(VALUE);x['jobs']=tuple(x['jobs']);variants.append(x)
  for x in variants:self.reject(x)
 def test_duplicate_nonfinite_and_non_json_values_reject(self):
  with self.assertRaisesRegex(DesignError,'JSON_DUPLICATE_KEY'):strict_json_loads('{"outer":{"x":1,"x":2}}')
  for text in ('{"x":NaN}','{"x":Infinity}','{"x":-Infinity}'):
   with self.assertRaises(DesignError):strict_json_loads(text)
  for value in (math.nan,math.inf,-math.inf):
   with self.assertRaises(DesignError):canonical_bytes({'x':value})
  with self.assertRaises(DesignError):canonical_bytes({'x':object()})
 def test_installed_activation_countability_and_effects_always_inert(self):
  for key,value in [('activation',True),('countable',True),('installed_jobs',['x']),('installed_schedules',['x'])]:x=copy.deepcopy(VALUE);x[key]=value;self.reject(x)
 def test_frozen_integration_and_old_evidence_unchanged(self):
  closure=ROOT/'tuning/architecture/r6_data_quality_fable_allocation_integration_v1/source-closure-v1.json';self.assertEqual(hashlib.sha256(closure.read_bytes()).hexdigest(),'3e7eb079ad924500f448517819845c30ed7a673c75d05288f6c46e6d166db893')
  old=json.loads((ROOT/'tuning/architecture/r6_data_quality_attempt_envelope_v1/source-closure-v6.json').read_text())
  for member in old['members']:
   raw=(ROOT/member['path']).read_bytes();self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(member['bytes'],member['sha256']))
 def test_pure_unreferenced_source_has_no_runtime_imports(self):
  path=ROOT/'shared/job_runtime/candidates/r6_data_quality_fable_allocation_design_v1/design.py';tree=ast.parse(path.read_text());imports=set()
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):imports.update(x.name.split('.')[0] for x in node.names)
   elif isinstance(node,ast.ImportFrom) and node.module:imports.add(node.module.split('.')[0])
  self.assertEqual(imports,{'__future__','hashlib','json','math','types','typing'})
  refs=[]
  for source in (ROOT/'shared/job_runtime').glob('*.py'):
   if 'r6_data_quality_fable_allocation_design_v1' in source.read_text():refs.append(source)
  self.assertEqual(refs,[])
if __name__=='__main__':unittest.main()
