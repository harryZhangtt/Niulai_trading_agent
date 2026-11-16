import ast,json,os,sqlite3,tempfile,unittest
from datetime import datetime
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_fable_v2_semantic_vertical_v1.vertical import VerticalError,execute,PROMPT_SHA
from shared.job_runtime.config import load
from shared.job_runtime.engine import validate_job
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
R=Path(__file__).resolve().parents[5];F=R/'shared/job_runtime/tests/fixtures/r6_data_quality_fable_v2_semantic_vertical_v1';V=json.loads((F/'vertical-input-v1.json').read_text());SOURCE=R/'mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-payload-v1.json'
def dt(x):return datetime.fromisoformat(x.replace('Z','+00:00'))
class T(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(dir=F);self.addCleanup(self.t.cleanup);self.r=Path(self.t.name);self.db=self.r/'closed.sqlite';c=sqlite3.connect(self.db);c.execute('create table provider_results(x text)');c.executemany('insert into provider_results values(?)',[('a',),('b',)]);c.commit();c.close();self.db.chmod(0o600)
 def runv(self,**kw):return execute(source_path=kw.get('source',SOURCE),closed_db=self.db,output_root=kw.get('root',self.r/'out'),rows=V['rows'],evaluation=dt(V['evaluation']),not_before=dt(V['not_before']),scheduled=dt(V['scheduled']),deadline=dt(V['deadline']),fault=kw.get('fault'))
 def test_nominal_full_semantic_chain_real_config_and_engine(self):
  out=self.runv();self.assertEqual((out['prompt']['bytes'],out['prompt']['sha256']),(526,PROMPT_SHA));self.assertEqual((out['ab']['denominator_count'],out['ab']['publication_attempts']),(2,0));self.assertEqual((out['budget']['per_arm_max_budget_usd'],out['budget']['aggregate_ceiling_usd'],out['budget']['status'],out['budget']['prompt_utf8_bytes'],out['budget']['token_evidence']),(0.02,0.04,'PROPOSED_UNAPPROVED',526,'UNMEASURED'))
  w=self.r/'workspace';state=w/'.job-runtime/config';state.mkdir(parents=True);(w/'.job-runtime').chmod(0o700);state.chmod(0o700);auth=state/'fable-v2-auth';auth.mkdir();auth.chmod(0o700);prompts=state/'prompts';prompts.mkdir();prompts.chmod(0o700);prompt=json.loads(SOURCE.read_text())['prompt_utf8'].encode();pf=prompts/'fable-v2.txt';pf.write_bytes(prompt);pf.chmod(0o600);ap=w/out['config']['allocation_files'][0];ap.write_text(json.dumps(out['allocation']));ap.chmod(0o600);cp=state/'config.json';cp.write_text(json.dumps(out['config']));cp.chmod(0o600);cwd=os.getcwd();os.chdir(w)
  try:config,jobs=load(cp,w)
  finally:os.chdir(cwd)
  self.assertEqual([(j['_prompt_capture'].length,j['_prompt_capture'].sha256) for j in jobs],[(526,PROMPT_SHA)]*2)
  for j in jobs:
   a=PromptArtifactDescriptorV1(1,'pa1:sha256:'+PROMPT_SHA+':526',PROMPT_SHA,526,'26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a','schema9-isolated-canary-q1-ab-payload-v1','native_v1');candidate={**{k:v for k,v in j.items() if k!='_prompt_capture'},'replay_safe':False,'_provider':'claude_host','_retry_policy':out['config']['retry'],'_prompt_artifact':a,'_resource_key':'fable-v2-serialized'};validate_job(candidate)
 def test_each_boundary_fault_and_source_symlink(self):
  for fault in ('prompt','adapter','bridge','integration','materialization','proposal','config'):
   with self.assertRaises(VerticalError):self.runv(fault=fault,root=self.r/('out-'+fault))
  link=self.r/'source-link';link.symlink_to(SOURCE)
  with self.assertRaises(VerticalError):self.runv(source=link,root=self.r/'out-link')
 def test_static_zero_effects(self):
  tree=ast.parse((R/'shared/job_runtime/candidates/r6_data_quality_fable_v2_semantic_vertical_v1/vertical.py').read_text());imports=set()
  for n in ast.walk(tree):
   if isinstance(n,ast.Import):imports.update(x.name.split('.')[0] for x in n.names)
   elif isinstance(n,ast.ImportFrom) and n.module:imports.add(n.module.split('.')[0])
  self.assertTrue(imports.isdisjoint({'requests','urllib','socket','smtplib','subprocess','service','provider'}))
if __name__=='__main__':unittest.main()
