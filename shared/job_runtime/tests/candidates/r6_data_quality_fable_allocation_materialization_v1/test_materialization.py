from __future__ import annotations
import ast,copy,hashlib,json,math,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_fable_allocation_materialization_v1.materialization import MaterializationError,canonical_bytes,default_materialization,render_materialization,strict_json_loads,validate_materialized
ROOT=Path(__file__).resolve().parents[5];FIX=ROOT/'shared/job_runtime/tests/fixtures';DESIGN=json.loads((FIX/'r6_data_quality_fable_allocation_design_v1/allocation-design-v1.json').read_text());TIMES=json.loads((FIX/'r6_data_quality_fable_allocation_materialization_v1/temporal-input-v1.json').read_text());EXPECTED=json.loads((FIX/'r6_data_quality_fable_allocation_materialization_v1/materialized-v1.json').read_text())
def dt(text):return datetime.fromisoformat(text.replace('Z','+00:00'))
def thaw(v):
 if hasattr(v,'items'):return {k:thaw(x) for k,x in v.items()}
 if isinstance(v,tuple):return [thaw(x) for x in v]
 return v
def render(**changes):
 values=dict(TIMES);values.update(changes);return render_materialization(DESIGN,dt(values['evaluation_time']) if isinstance(values['evaluation_time'],str) else values['evaluation_time'],dt(values['not_before']) if isinstance(values['not_before'],str) else values['not_before'],dt(values['deadline']) if isinstance(values['deadline'],str) else values['deadline'],dt(values['scheduled_at']) if isinstance(values['scheduled_at'],str) else values['scheduled_at'],grace_seconds=values['grace_seconds'])
class MaterializationTests(unittest.TestCase):
 def reject_doc(self,value):
  with self.assertRaises(MaterializationError):validate_materialized(value)
 def test_nominal_fixture_digest_immutable_and_default_deny(self):
  out=render();document=thaw(out.document);self.assertEqual(document,EXPECTED['document']);self.assertEqual(out.sha256,EXPECTED['sha256']);self.assertEqual(hashlib.sha256(canonical_bytes(document)).hexdigest(),out.sha256);validate_materialized(document)
  with self.assertRaises(TypeError):out.document['activation']=True
  default=default_materialization();self.assertFalse(default['activation']);self.assertTrue(all(x==0 for x in default['effects'].values()))
 def test_exact_two_identical_disabled_once_jobs(self):
  document=copy.deepcopy(EXPECTED['document']);jobs=document['jobs'];self.assertEqual([x['schedule'] for x in jobs],[{'kind':'once','at':TIMES['scheduled_at'],'grace_seconds':240}]*2);self.assertTrue(all(x['enabled'] is False and x['replay_safe'] is False for x in jobs));self.assertEqual(document['execution'],{'max_workers':1,'resource_serialization':True,'resource_key':'fable-ab-serialized'});self.assertEqual(document['installed_jobs'],[]);self.assertEqual(document['installed_schedules'],[])
 def test_naive_and_non_utc_inputs_reject_zero_offset_normalizes(self):
  naive=datetime(2026,11,12,12,0)
  for key in ('evaluation_time','not_before','deadline','scheduled_at'):
   with self.assertRaises(MaterializationError):render(**{key:naive})
  nonutc=timezone(timedelta(hours=1))
  with self.assertRaises(MaterializationError):render(scheduled_at=datetime(2026,11,12,13,2,tzinfo=nonutc))
  zero=timezone(timedelta(0));out=render(scheduled_at=datetime(2026,11,12,12,2,tzinfo=zero));self.assertEqual(out.document['scheduled_at'],'2026-11-12T12:02:00Z')
 def test_every_temporal_field_requires_exact_whole_second_no_rounding(self):
  base={key:dt(TIMES[key]) for key in ('evaluation_time','not_before','scheduled_at','deadline')}
  for key in base:
   accepted=dict(base);accepted[key]=accepted[key].replace(microsecond=0);out=render(**accepted);self.assertEqual(out.document[key],TIMES[key])
   for micros in (1,500000,999999):
    changed=dict(base);changed[key]=changed[key].replace(microsecond=micros)
    with self.assertRaises(MaterializationError):render(**changed)
 def test_past_stale_and_time_order_reject(self):
  variants=[{'scheduled_at':TIMES['evaluation_time']},{'not_before':'2026-11-12T12:03:00Z'},{'deadline':'2026-11-12T12:01:30Z'},{'evaluation_time':'2026-11-12T12:03:00Z'}]
  for values in variants:
   with self.assertRaises(MaterializationError):render(**values)
 def test_offset_text_ambiguity_unequal_timestamp_interval_and_recurrence_reject(self):
  variants=[]
  x=copy.deepcopy(EXPECTED['document']);x['scheduled_at']='2026-11-12T12:02:00+00:00';variants.append(x)
  x=copy.deepcopy(EXPECTED['document']);x['jobs'][1]['schedule']['at']='2026-11-12T12:02:01Z';variants.append(x)
  for kind in ('interval','daily','cron','sequence'):
   x=copy.deepcopy(EXPECTED['document']);x['jobs'][0]['schedule']['kind']=kind;variants.append(x)
  for x in variants:self.reject_doc(x)
 def test_grace_and_total_window_overflow_reject(self):
  for grace in (0,301,241):
   with self.assertRaises(MaterializationError):render(grace_seconds=grace)
  with self.assertRaises(MaterializationError):render(deadline='2026-11-12T12:06:01Z')
  x=copy.deepcopy(EXPECTED['document']);x['jobs'][0]['schedule']['grace_seconds']=301;self.reject_doc(x)
  x=copy.deepcopy(EXPECTED['document']);x['window_seconds']=301;x['deadline']='2026-11-12T12:06:01Z';self.reject_doc(x)
 def test_order_asymmetry_prompt_closure_and_resource_drift_reject(self):
  variants=[]
  x=copy.deepcopy(EXPECTED['document']);x['jobs'].reverse();variants.append(x)
  x=copy.deepcopy(EXPECTED['document']);x['jobs'][1]['resource_key']='other';variants.append(x)
  x=copy.deepcopy(EXPECTED['document']);x['jobs'][0]['prompt_artifact']['sha256']='0'*64;variants.append(x)
  for key in ('design_sha256','integration_sha256','integration_closure_sha256','bridge_closure_sha256','adapter_closure_sha256'):
   x=copy.deepcopy(EXPECTED['document']);x[key]='0'*64;variants.append(x)
  for x in variants:self.reject_doc(x)
 def test_extra_missing_type_tamper_and_effect_drift_reject(self):
  document=EXPECTED['document']
  for key in document:
   x=copy.deepcopy(document);x.pop(key);self.reject_doc(x)
  x=copy.deepcopy(document);x['extra']=1;self.reject_doc(x)
  variants=[]
  x=copy.deepcopy(document);x['version']=True;variants.append(x)
  x=copy.deepcopy(document);x['window_seconds']=300.0;variants.append(x)
  x=copy.deepcopy(document);x['jobs'][0]['limits']['attempts']=True;variants.append(x)
  x=copy.deepcopy(document);x['jobs']=tuple(x['jobs']);variants.append(x)
  x=copy.deepcopy(document);x['effects']['provider']=1;variants.append(x)
  x=copy.deepcopy(document);x['activation']=True;variants.append(x)
  for x in variants:self.reject_doc(x)
 def test_duplicate_nonfinite_and_source_design_tamper_reject(self):
  with self.assertRaisesRegex(MaterializationError,'JSON_DUPLICATE_KEY'):strict_json_loads('{"x":{"a":1,"a":2}}')
  for text in ('{"x":NaN}','{"x":Infinity}','{"x":-Infinity}'):
   with self.assertRaises(MaterializationError):strict_json_loads(text)
  for value in (math.nan,math.inf,-math.inf):
   with self.assertRaises(MaterializationError):canonical_bytes({'x':value})
  design=copy.deepcopy(DESIGN);design['activation']=True
  with self.assertRaises(MaterializationError):render_materialization(design,dt(TIMES['evaluation_time']),dt(TIMES['not_before']),dt(TIMES['deadline']),dt(TIMES['scheduled_at']),grace_seconds=240)
 def test_pure_unreferenced_no_runtime_imports(self):
  path=ROOT/'shared/job_runtime/candidates/r6_data_quality_fable_allocation_materialization_v1/materialization.py';tree=ast.parse(path.read_text());imports=set()
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):imports.update(x.name.split('.')[0] for x in node.names)
   elif isinstance(node,ast.ImportFrom) and node.module:imports.add(node.module.split('.')[0])
  self.assertEqual(imports,{'__future__','dataclasses','datetime','hashlib','json','math','types','typing'})
  forbidden=('engine','scheduler','service','allocation','integration','bridge','adapter','provider')
  self.assertTrue(imports.isdisjoint(forbidden));self.assertEqual([p for p in (ROOT/'shared/job_runtime').glob('*.py') if 'r6_data_quality_fable_allocation_materialization_v1' in p.read_text()],[])
if __name__=='__main__':unittest.main()
