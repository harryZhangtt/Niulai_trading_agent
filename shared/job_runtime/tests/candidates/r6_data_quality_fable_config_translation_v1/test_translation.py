from __future__ import annotations
import ast,copy,hashlib,json,math,os,tempfile,unittest
from datetime import datetime,timedelta
from pathlib import Path
from shared.job_runtime.config import load_projection
from shared.job_runtime.engine import validate_job
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.candidates.r6_data_quality_fable_config_translation_v1.translation import TranslationError,canonical_bytes,default_translation,render_translation,strict_json_loads,validate_translation
ROOT=Path(__file__).resolve().parents[5];FIX=ROOT/'shared/job_runtime/tests/fixtures';INPUT=json.loads((FIX/'r6_data_quality_fable_config_translation_v1/translation-input-v1.json').read_text());EXPECTED=json.loads((FIX/'r6_data_quality_fable_config_translation_v1/translation-v1.json').read_text())
def dt(text):return datetime.fromisoformat(text.replace('Z','+00:00'))
def thaw(v):
 if hasattr(v,'items'):return {k:thaw(x) for k,x in v.items()}
 if isinstance(v,tuple):return [thaw(x) for x in v]
 return v
def render(**changes):
 values=dict(INPUT);values.update(changes);return render_translation(values['proposal'],values['proposal_sha256'],values.get('current',dt(values['current_evaluation_time'])),values['prompt_custody'])
class TranslationTests(unittest.TestCase):
 def setUp(self):
  private=FIX/'r6_data_quality_fable_config_translation_v1/.runtime';private.mkdir(mode=0o700,parents=True,exist_ok=True);self.tmp=tempfile.TemporaryDirectory(dir=private);self.addCleanup(self.tmp.cleanup);self.workspace=Path(self.tmp.name);self.state=self.workspace/'.job-runtime/config';self.state.mkdir(mode=0o700,parents=True);(self.workspace/'.job-runtime').chmod(0o700);self.state.chmod(0o700);(self.state/'fable-auth-home').mkdir(mode=0o700);(self.state/'fable-auth-home').chmod(0o700);(self.state/'prompts').mkdir(mode=0o700);(self.state/'prompts').chmod(0o700);(self.state/'prompts/fable-ab.txt').write_bytes(b'x');(self.state/'prompts/fable-ab.txt').chmod(0o600)
 def test_nominal_fixture_digest_default_deny_and_budget_fence(self):
  out=render();self.assertEqual((thaw(out.config),thaw(out.allocation),thaw(out.injection),thaw(out.budget),out.sha256),(EXPECTED['config'],EXPECTED['allocation'],EXPECTED['injection'],EXPECTED['budget'],EXPECTED['sha256']));validate_translation(thaw(out.config),thaw(out.allocation),thaw(out.injection),thaw(out.budget));self.assertFalse(out.budget['budget_approved']);self.assertFalse(out.budget['billed_authority']);self.assertEqual(out.budget['prompt_token_evidence']['status'],'PLACEHOLDER_UNVERIFIED');self.assertFalse(default_translation()['activation'])
 def test_real_config_projection_and_engine_job_validation_disposable(self):
  out=render();config=thaw(out.config);allocation=thaw(out.allocation);injection=thaw(out.injection);allocation_path=self.workspace/config['allocation_files'][0];allocation_path.write_text(json.dumps(allocation));allocation_path.chmod(0o600);config_path=self.state/'candidate.json';config_path.write_text(json.dumps(config));config_path.chmod(0o600);previous=os.getcwd();os.chdir(self.workspace)
  try:loaded,jobs=load_projection(config_path,self.workspace)
  finally:os.chdir(previous)
  self.assertEqual(len(jobs),2)
  for i,job in enumerate(jobs):
   inject=injection['jobs'][i];artifact=PromptArtifactDescriptorV1(**inject['_prompt_artifact']);candidate={**job,'replay_safe':False,'_provider':inject['_provider'],'_retry_policy':inject['_retry_policy'],'_prompt_artifact':artifact,'_resource_key':inject['_resource_key'],'_circuit_scope':inject['_circuit_scope']};validate_job(candidate);self.assertFalse(candidate['enabled']);self.assertEqual(candidate['schedule'],jobs[0]['schedule'])
 def test_exact_profile_retry_no_fallback_unique_ids_scopes_shared_resource(self):
  out=render();config=thaw(out.config);allocation=thaw(out.allocation);inject=thaw(out.injection);profile=config['model_profiles']['fable-ab-disabled'];self.assertEqual((profile['provider'],profile['model'],profile['effort'],profile['timeout_seconds']),('claude_host','claude-fable-5-1','low',300));self.assertNotIn('fallback',json.dumps(config).lower());self.assertEqual(config['retry']['max_attempts'],1);self.assertEqual(len({j['id'] for j in allocation['jobs']}),2);self.assertEqual(len({j['replay_contract']['slot_operation_scope'] for j in allocation['jobs']}),2);self.assertEqual({j['_resource_key'] for j in inject['jobs']},{'fable-ab-serialized'});self.assertEqual(config['max_workers'],1)
 def test_proposal_hash_stale_current_custody_and_closure_drift_reject(self):
  with self.assertRaises(TranslationError):render(proposal_sha256='0'*64)
  with self.assertRaises(TranslationError):render(current=dt(INPUT['proposal']['materialized_lineage']['scheduled_at']))
  with self.assertRaises(TranslationError):render(current=dt(INPUT['current_evaluation_time']).replace(microsecond=1))
  for key,value in [('sha256','0'*64),('mode','0644'),('owner_verified',False),('no_symlink',False),('source_generation','other')]:
   custody=copy.deepcopy(INPUT['prompt_custody']);custody[key]=value
   with self.assertRaises(TranslationError):render(prompt_custody=custody)
  proposal=copy.deepcopy(INPUT['proposal']);proposal['integration_closure_sha256']='0'*64
  with self.assertRaises(TranslationError):render(proposal=proposal,proposal_sha256=hashlib.sha256(canonical_bytes(proposal)).hexdigest())
 def test_schema_profile_retry_injection_and_budget_drift_reject(self):
  out=render();base=[thaw(out.config),thaw(out.allocation),thaw(out.injection),thaw(out.budget)];variants=[]
  x=copy.deepcopy(base);x[0]['schema_version']=1;variants.append(x)
  x=copy.deepcopy(base);x[0]['model_profiles']['fable-ab-disabled']['provider']='codex_cli';variants.append(x)
  x=copy.deepcopy(base);x[0]['retry']['max_attempts']=2;variants.append(x)
  x=copy.deepcopy(base);x[1]['jobs'][0]['enabled']=True;variants.append(x)
  x=copy.deepcopy(base);x[1]['jobs'][0]['schedule']['kind']='interval';variants.append(x)
  x=copy.deepcopy(base);x[2]['jobs'][0]['_provider']='codex_cli';variants.append(x)
  x=copy.deepcopy(base);x[3]['budget_approved']=True;variants.append(x)
  x=copy.deepcopy(base);x[3]['prompt_token_evidence']['status']='VERIFIED';variants.append(x)
  for values in variants:
   with self.assertRaises(TranslationError):validate_translation(*values)
 def test_active_attempt_replay_status_tool_and_fallback_drift_reject(self):
  out=render();base=[thaw(out.config),thaw(out.allocation),thaw(out.injection),thaw(out.budget)]
  for key,value in [('max_attempts',2),('retries',1),('replays',1),('status_queries',1),('tools',1),('web',1),('subagents',1),('fallbacks',1)]:
   values=copy.deepcopy(base);values[2]['jobs'][0]['_retry_policy'][key]=value if key in values[2]['jobs'][0]['_retry_policy'] else values[2]['jobs'][0]['_retry_policy'].get(key); 
   if key not in ('max_attempts',):values[1]['jobs'][0][key]=value
   with self.assertRaises(TranslationError):validate_translation(*values)
 def test_duplicate_nonfinite_types_and_extra_missing_reject(self):
  with self.assertRaisesRegex(TranslationError,'JSON_DUPLICATE_KEY'):strict_json_loads('{"x":{"a":1,"a":2}}')
  for text in ('{"x":NaN}','{"x":Infinity}','{"x":-Infinity}'):
   with self.assertRaises(TranslationError):strict_json_loads(text)
  for value in (math.nan,math.inf,-math.inf):
   with self.assertRaises(TranslationError):canonical_bytes({'x':value})
  out=render();base=[thaw(out.config),thaw(out.allocation),thaw(out.injection),thaw(out.budget)]
  x=copy.deepcopy(base);x[0]['max_workers']=True
  with self.assertRaises(TranslationError):validate_translation(*x)
  x=copy.deepcopy(base);x[3]['extra']=0
  with self.assertRaises(TranslationError):validate_translation(*x)
 def test_pure_unreferenced_no_runtime_imports_or_writes(self):
  path=ROOT/'shared/job_runtime/candidates/r6_data_quality_fable_config_translation_v1/translation.py';tree=ast.parse(path.read_text());imports=set()
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):imports.update(x.name.split('.')[0] for x in node.names)
   elif isinstance(node,ast.ImportFrom) and node.module:imports.add(node.module.split('.')[0])
  self.assertEqual(imports,{'__future__','dataclasses','datetime','hashlib','json','math','types','typing'});self.assertEqual([p for p in (ROOT/'shared/job_runtime').glob('*.py') if 'r6_data_quality_fable_config_translation_v1' in p.read_text()],[])
if __name__=='__main__':unittest.main()
