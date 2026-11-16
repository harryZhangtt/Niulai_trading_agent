from __future__ import annotations
import ast,copy,hashlib,json,math,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_fable_installation_proposal_v1.proposal import ProposalError,canonical_bytes,default_proposal,render_proposal,strict_json_loads,validate_proposal
ROOT=Path(__file__).resolve().parents[5];FIX=ROOT/'shared/job_runtime/tests/fixtures';MAT=json.loads((FIX/'r6_data_quality_fable_allocation_materialization_v1/materialized-v1.json').read_text());INPUT=json.loads((FIX/'r6_data_quality_fable_installation_proposal_v1/proposal-input-v1.json').read_text());EXPECTED=json.loads((FIX/'r6_data_quality_fable_installation_proposal_v1/proposal-v1.json').read_text())
def dt(text):return datetime.fromisoformat(text.replace('Z','+00:00'))
def thaw(v):
 if hasattr(v,'items'):return {k:thaw(x) for k,x in v.items()}
 if isinstance(v,tuple):return [thaw(x) for x in v]
 return v
def render(current=None,custody=None,materialized=None,digest=None):return render_proposal((materialized or MAT)['document'],digest or INPUT['materialized_sha256'],current or dt(INPUT['current_evaluation_time']),custody or INPUT['prompt_custody'])
class ProposalTests(unittest.TestCase):
 def reject(self,value):
  with self.assertRaises(ProposalError):validate_proposal(value)
 def test_nominal_schema_digest_immutable_and_default_deny(self):
  out=render();document=thaw(out.document);self.assertEqual((document,out.schema,out.sha256),(EXPECTED['document'],EXPECTED['schema'],EXPECTED['sha256']));self.assertEqual(hashlib.sha256(canonical_bytes(document)).hexdigest(),out.sha256);validate_proposal(document)
  with self.assertRaises(TypeError):out.document['apply']=True
  default=default_proposal();self.assertFalse(default['apply']);self.assertTrue(all(x==0 for x in default['effects'].values()))
 def test_exact_engine_facing_disabled_data_symmetry(self):
  jobs=EXPECTED['document']['jobs'];self.assertEqual([x['id'] for x in jobs],['fable-adapter-cell-0','fable-adapter-cell-1']);self.assertTrue(all(x['enabled'] is False and x['replay_safe'] is False and x['schedule']['kind']=='once' for x in jobs));self.assertEqual(jobs[0]['schedule'],jobs[1]['schedule']);self.assertEqual(jobs[0]['execution_limits'],{'max_attempts':1,'retries':0,'replays':0,'status_queries':0,'tools':0,'web':0,'subagents':0,'fallbacks':0});self.assertEqual(EXPECTED['document']['installed_jobs'],[]);self.assertEqual(EXPECTED['document']['installed_schedules'],[])
 def test_stale_past_nonwhole_naive_nonutc_and_horizon_reject(self):
  scheduled=dt(MAT['document']['scheduled_at'])
  for current in (scheduled,scheduled+timedelta(seconds=1),datetime(2026,11,12,12,0,30),datetime(2026,11,12,13,0,30,tzinfo=timezone(timedelta(hours=1))),dt(INPUT['current_evaluation_time']).replace(microsecond=1),scheduled-timedelta(seconds=301)):
   with self.assertRaises(ProposalError):render(current=current)
 def test_due_grace_id_collision_recurrence_and_unequal_arms_reject(self):
  variants=[]
  x=copy.deepcopy(EXPECTED['document']);x['jobs'][1]['id']=x['jobs'][0]['id'];variants.append(x)
  x=copy.deepcopy(EXPECTED['document']);x['jobs'][1]['schedule']['at']='2026-11-12T12:02:01Z';variants.append(x)
  x=copy.deepcopy(EXPECTED['document']);x['jobs'][0]['schedule']['grace_seconds']=239;variants.append(x)
  for kind in ('interval','daily','cron','sequence'):
   x=copy.deepcopy(EXPECTED['document']);x['jobs'][0]['schedule']['kind']=kind;variants.append(x)
  for x in variants:self.reject(x)
 def test_exact_materialized_lineage_pre_evaluation_and_symmetric_schedule_drift_reject(self):
  self.assertEqual(INPUT['materialized'],MAT['document']);self.assertEqual(EXPECTED['document']['classification'],'DATA_ONLY_NOT_CONFIG_V2_NOT_ENGINE_INSTALLABLE');self.assertEqual(EXPECTED['document']['materialized_lineage'],{'evaluation_time':MAT['document']['evaluation_time'],'not_before':MAT['document']['not_before'],'scheduled_at':MAT['document']['scheduled_at'],'deadline':MAT['document']['deadline'],'grace_seconds':MAT['document']['jobs'][0]['schedule']['grace_seconds']})
  with self.assertRaises(ProposalError):render(current=dt(MAT['document']['evaluation_time'])-timedelta(seconds=1))
  variants=[]
  x=copy.deepcopy(EXPECTED['document'])
  for job in x['jobs']:job['schedule']['at']='2026-11-12T12:02:01Z'
  variants.append(x)
  x=copy.deepcopy(EXPECTED['document'])
  for job in x['jobs']:job['schedule']['grace_seconds']=239
  variants.append(x)
  x=copy.deepcopy(EXPECTED['document'])
  for job in x['jobs']:job['schedule']['grace_seconds']=241
  variants.append(x)
  for key,value in [('not_before','2026-11-12T12:01:01Z'),('deadline','2026-11-12T12:05:59Z'),('scheduled_at','2026-11-12T12:02:01Z')]:
   x=copy.deepcopy(EXPECTED['document']);x['materialized_lineage'][key]=value;variants.append(x)
  for x in variants:self.reject(x)
 def test_provider_replay_retry_resource_and_prompt_descriptor_drift_reject(self):
  variants=[]
  for key,value in [('provider','codex_cli'),('provider_profile','other'),('model','claude-opus-5-5'),('replay_safe',True),('resource_key','other')]:x=copy.deepcopy(EXPECTED['document']);x['jobs'][0][key]=value;variants.append(x)
  for key,value in [('max_attempts',2),('retries',1),('status_queries',1),('fallbacks',1)]:x=copy.deepcopy(EXPECTED['document']);x['jobs'][0]['execution_limits'][key]=value;variants.append(x)
  for key,value in [('sha256','0'*64),('ref','other'),('source_identity_sha256','0'*64),('generation','other')]:x=copy.deepcopy(EXPECTED['document']);x['jobs'][0]['prompt_artifact'][key]=value;variants.append(x)
  for x in variants:self.reject(x)
 def test_custody_absence_hash_mode_owner_symlink_generation_drift_reject(self):
  keys=INPUT['prompt_custody'].keys()
  for key in keys:
   x=copy.deepcopy(INPUT['prompt_custody']);x.pop(key)
   with self.assertRaises(ProposalError):render(custody=x)
  mutations=[('logical_path','other'),('sha256','0'*64),('bytes',2),('mode','0644'),('owner_uid',-1),('owner_uid',True),('owner_verified',False),('no_symlink',False),('source_generation','other')]
  for key,value in mutations:
   x=copy.deepcopy(INPUT['prompt_custody']);x[key]=value
   with self.assertRaises(ProposalError):render(custody=x)
 def test_closure_schema_apply_effect_asymmetry_and_extra_missing_reject(self):
  document=EXPECTED['document'];variants=[]
  for key in ('materialized_sha256','materialization_closure_sha256','design_sha256','integration_sha256','integration_closure_sha256','bridge_closure_sha256','adapter_closure_sha256'):
   x=copy.deepcopy(document);x[key]='0'*64;variants.append(x)
  for key,value in [('schema','other'),('activation',True),('apply',True),('countable',True)]:x=copy.deepcopy(document);x[key]=value;variants.append(x)
  x=copy.deepcopy(document);x['effects']['provider']=1;variants.append(x)
  for x in variants:self.reject(x)
  for key in document:
   x=copy.deepcopy(document);x.pop(key);self.reject(x)
  x=copy.deepcopy(document);x['extra']=0;self.reject(x)
 def test_materialized_hash_job_prompt_and_deadline_tamper_reject(self):
  with self.assertRaises(ProposalError):render(digest='0'*64)
  for mutation in ('job','prompt','deadline'):
   x=copy.deepcopy(MAT)
   if mutation=='job':x['document']['jobs'][0]['job_id']='other'
   elif mutation=='prompt':x['document']['jobs'][0]['prompt_artifact']['sha256']='0'*64
   else:x['document']['deadline']='2026-11-12T12:01:00Z'
   with self.assertRaises(ProposalError):render(materialized=x,digest=hashlib.sha256(canonical_bytes(x['document'])).hexdigest())
 def test_duplicate_nonfinite_and_type_aliases_reject(self):
  with self.assertRaisesRegex(ProposalError,'JSON_DUPLICATE_KEY'):strict_json_loads('{"x":{"a":1,"a":2}}')
  for text in ('{"x":NaN}','{"x":Infinity}','{"x":-Infinity}'):
   with self.assertRaises(ProposalError):strict_json_loads(text)
  for value in (math.nan,math.inf,-math.inf):
   with self.assertRaises(ProposalError):canonical_bytes({'x':value})
  variants=[]
  x=copy.deepcopy(EXPECTED['document']);x['version']=True;variants.append(x)
  x=copy.deepcopy(EXPECTED['document']);x['approved_horizon_seconds']=300.0;variants.append(x)
  x=copy.deepcopy(EXPECTED['document']);x['jobs'][0]['execution_limits']['max_attempts']=True;variants.append(x)
  for x in variants:self.reject(x)
 def test_pure_unreferenced_no_runtime_imports_or_writes(self):
  path=ROOT/'shared/job_runtime/candidates/r6_data_quality_fable_installation_proposal_v1/proposal.py';tree=ast.parse(path.read_text());imports=set()
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):imports.update(x.name.split('.')[0] for x in node.names)
   elif isinstance(node,ast.ImportFrom) and node.module:imports.add(node.module.split('.')[0])
  self.assertEqual(imports,{'__future__','dataclasses','datetime','hashlib','json','math','types','typing'});self.assertTrue(imports.isdisjoint({'engine','scheduler','service','allocation','integration','bridge','adapter','provider','os','pathlib'}));self.assertEqual([p for p in (ROOT/'shared/job_runtime').glob('*.py') if 'r6_data_quality_fable_installation_proposal_v1' in p.read_text()],[])
if __name__=='__main__':unittest.main()
