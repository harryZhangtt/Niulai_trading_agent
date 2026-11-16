import copy,json,unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_fable_config_translation_v2.manifest import validate,MANIFEST_SHA256
R=Path(__file__).resolve().parents[5];V=json.loads((R/"shared/job_runtime/tests/fixtures/r6_data_quality_fable_config_translation_v2/manifest-v2.json").read_text())
class T(unittest.TestCase):
 def test_exact(self):self.assertEqual(validate(copy.deepcopy(V)),V)
 def test_drift(self):
  x=copy.deepcopy(V);x["prompt"]["bytes"]=1
  with self.assertRaises(Exception):validate(x)
if __name__=="__main__":unittest.main()

class RealPromptAndConfig(unittest.TestCase):
 def test_real_prompt_full_loader_and_engine_binding(self):
  import hashlib,os,tempfile
  from shared.job_runtime.config import load
  from shared.job_runtime.engine import validate_job
  from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
  from shared.job_runtime.provider_contract import ReplayContractV1
  R=Path(__file__).resolve().parents[5];source=R/'mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-payload-v1.json';info=source.lstat();self.assertFalse(source.is_symlink());self.assertEqual((info.st_uid,info.st_mode&0o777),(os.getuid(),0o644));source_raw=source.read_bytes();self.assertEqual(hashlib.sha256(source_raw).hexdigest(),V['prompt']['source_sha256']);prompt=json.loads(source_raw)['prompt_utf8'].encode('utf-8');self.assertEqual((len(prompt),hashlib.sha256(prompt).hexdigest()),(526,V['prompt']['sha256']))
  with tempfile.TemporaryDirectory(dir=R/'shared/job_runtime/tests/fixtures'/V['stage']) as td:
   w=Path(td);state=w/'.job-runtime/config';state.mkdir(parents=True);(w/'.job-runtime').chmod(0o700);state.chmod(0o700);auth=state/'fable-v2-auth';auth.mkdir();auth.chmod(0o700);prompts=state/'prompts';prompts.mkdir();prompts.chmod(0o700);pf=prompts/'fable-v2.txt';pf.write_bytes(prompt);pf.chmod(0o600);alloc=w/V['payload']['config']['allocation_files'][0];alloc.write_text(json.dumps(V['payload']['allocation']));alloc.chmod(0o600);cfg=state/'candidate.json';cfg.write_text(json.dumps(V['payload']['config']));cfg.chmod(0o600);cwd=os.getcwd();os.chdir(w)
   try:config,jobs=load(cfg,w)
   finally:os.chdir(cwd)
   self.assertEqual([(x['_prompt_capture'].length,x['_prompt_capture'].sha256) for x in jobs],[(526,V['prompt']['sha256'])]*2)
   for i,job in enumerate(jobs):
    inj=V['payload']['injection']['jobs'][i];candidate={**{k:v for k,v in job.items() if k!='_prompt_capture'},'replay_safe':False,'_provider':inj['_provider'],'_retry_policy':inj['_retry_policy'],'_prompt_artifact':PromptArtifactDescriptorV1(**inj['_prompt_artifact']),'_resource_key':inj['_resource_key']};validate_job(candidate)
