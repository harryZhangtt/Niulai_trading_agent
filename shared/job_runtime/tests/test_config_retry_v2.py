import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.job_runtime.config import ConfigError, load, prompt_file
from shared.job_runtime.prompt_custody import CapturedPromptV1
from shared.job_runtime.provider_contract import ReplayContractV1
from shared.job_runtime.retry_policy import RetryPolicyV2
from shared.job_runtime.service import resource_jobs


class ConfigRetryV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name).resolve()
        self.state = self.workspace / '.job-runtime'
        self.state.mkdir(mode=0o700); self.state.chmod(0o700)
        self.auth = self.state / 'auth'
        self.auth.mkdir(mode=0o700); self.auth.chmod(0o700)
        (self.auth/'auth.json').write_text('{}'); (self.auth/'auth.json').chmod(0o600)
        self.prompt_dir = self.state / 'config'
        self.prompt_dir.mkdir(mode=0o700); self.prompt_dir.chmod(0o700)
        self.prompt = self.prompt_dir / 'prompt.md'
        self.prompt.write_text('prompt'); self.prompt.chmod(0o600)
        self.prompt_relative = '.job-runtime/config/prompt.md'

    def tearDown(self):
        self.temp.cleanup()

    def private_prompt(self, relative='visible-proof-prompt.txt', area='config'):
        directory=self.state/area
        directory.mkdir(mode=0o700,exist_ok=True); directory.chmod(0o700)
        prompt=directory/relative
        prompt.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        for ancestor in [prompt.parent,*prompt.parent.parents]:
            if ancestor == self.state:
                break
            ancestor.chmod(0o700)
        prompt.write_text('private prompt'); prompt.chmod(0o600)
        return prompt, f'.job-runtime/{area}/{relative}'

    def write(self, version=2, *, job_update=None, profile_update=None,
              retry_update=None, allocation_version=None):
        profile={'provider':'codex_cli','codex_bin':'/bin/true','model':'gpt-test',
                 'effort':'medium','timeout_seconds':10,'auth_home':str(self.auth)}
        if profile_update: profile.update(profile_update)
        retry={'version':2,'max_attempts':3,'base_delay_seconds':1,
               'max_delay_seconds':30}
        if retry_update: retry.update(retry_update)
        job={'id':'job','enabled':True,'schedule':{'kind':'interval','seconds':60},
             'model_profile':'primary','prompt_file':self.prompt_relative,
             'replay_contract':{'version':1,'effect':'none',
                 'automatic_phases':['not_started','connecting'],
                 'slot_operation_scope':'job/slot','reconciliation_adapter':None}}
        if job_update: job.update(job_update)
        allocation={'schema_version':allocation_version or version,'jobs':[job]}
        (self.workspace/'allocation.json').write_text(json.dumps(allocation))
        config={'schema_version':version,'tick_seconds':1,'heartbeat_seconds':1,
                'stale_seconds':30,'max_workers':1,'retry':retry,
                'model_profiles':{'primary':profile},
                'allocation_files':['allocation.json'],'source_paths':[]}
        path=self.state/'config.json'; path.write_text(json.dumps(config)); path.chmod(0o600)
        return path,config,allocation

    def test_v2_builds_typed_engine_fields_with_hashed_resource(self):
        path,_,_=self.write()
        config,jobs=load(path,self.workspace)
        captured=jobs[0]['_prompt_capture']
        self.assertIsInstance(captured,CapturedPromptV1)
        self.assertEqual((captured.raw,captured.sha256,captured.length),
                         (b'prompt',hashlib.sha256(b'prompt').hexdigest(),6))
        rendered=repr(captured)
        self.assertEqual(rendered,'CapturedPromptV1(<redacted>)')
        self.assertNotIn(captured.raw.decode(),rendered)
        self.assertNotIn(captured.sha256,rendered)
        prepared=resource_jobs(config,jobs)[0]
        self.assertIs(prepared['_prompt_capture'],captured)
        self.assertNotIn('_prompt_snapshot',prepared)
        self.assertNotIn('_prompt_sha256',prepared)
        self.assertIsInstance(prepared['_retry_policy'],RetryPolicyV2)
        self.assertIsInstance(prepared['_replay_contract'],ReplayContractV1)
        self.assertEqual(prepared['_provider'],'codex_cli')
        self.assertRegex(prepared['_resource_key'],r'^[0-9a-f]{64}$')
        self.assertNotIn(str(self.auth),json.dumps({
            'resource':prepared['_resource_key'],'circuit':prepared['_circuit_scope']}))

    def test_v2_rejects_replay_safe_mixing_unknown_and_bad_retry(self):
        path,_,_=self.write(job_update={'replay_safe':True})
        with self.assertRaisesRegex(ConfigError,'JOB_KEYS_INVALID'): load(path,self.workspace)
        path,_,_=self.write(profile_update={'unknown':1})
        with self.assertRaisesRegex(ConfigError,'PROFILE_KEYS_INVALID'): load(path,self.workspace)
        path,_,_=self.write(retry_update={'extra':1})
        with self.assertRaisesRegex(ConfigError,'RETRY_POLICY_INVALID'): load(path,self.workspace)

    def test_owner_private_config_prompt_loads_for_v1_and_v2(self):
        _prompt,relative=self.private_prompt('nested/v3-proof.txt')
        path,_,_=self.write(job_update={'prompt_file':relative})
        _config,jobs=load(path,self.workspace)
        self.assertEqual(jobs[0]['prompt_file'],relative)

        profile={'auth_home':str(self.auth),'executor':'readiness'}
        job={'id':'legacy-private','enabled':True,
             'schedule':{'kind':'interval','seconds':60},'replay_safe':True,
             'model_profile':'primary','prompt_file':relative}
        allocation={'schema_version':1,'jobs':[job]}
        (self.workspace/'allocation.json').write_text(json.dumps(allocation))
        config={'schema_version':1,'tick_seconds':1,'heartbeat_seconds':1,
                'stale_seconds':30,'max_workers':1,
                'retry':{'max_attempts':1,'initial_delay_seconds':1,'max_delay_seconds':1},
                'model_profiles':{'primary':profile},'allocation_files':['allocation.json'],
                'source_paths':[]}
        path.write_text(json.dumps(config)); path.chmod(0o600)
        loaded,jobs=load(path,self.workspace)
        self.assertEqual(loaded,config); self.assertEqual(jobs,[job])

        _acceptance, acceptance_relative = self.private_prompt(
            'candidate-v1/prompt.txt', area='acceptance')
        allocation['jobs'][0]['prompt_file'] = acceptance_relative
        (self.workspace/'allocation.json').write_text(json.dumps(allocation))
        _loaded, jobs = load(path, self.workspace)
        self.assertEqual(jobs[0]['prompt_file'], acceptance_relative)

    def test_private_config_prompt_rejects_insecure_hidden_and_symlink_cases(self):
        prompt,relative=self.private_prompt()
        prompt.chmod(0o660)
        with self.assertRaisesRegex(ConfigError,'PROMPT_INVALID'):
            prompt_file(relative,self.workspace)
        prompt.chmod(0o600); prompt.parent.chmod(0o770)
        with self.assertRaisesRegex(ConfigError,'PROMPT_INVALID'):
            prompt_file(relative,self.workspace)
        prompt.parent.chmod(0o700)
        with patch('shared.job_runtime.config.os.getuid',return_value=os.getuid()+1), \
                self.assertRaisesRegex(ConfigError,'PROMPT_INVALID'):
            prompt_file(relative,self.workspace)

        target=self.prompt
        link=prompt.parent/'linked.txt'; link.symlink_to(target)
        with self.assertRaises(ConfigError):
            prompt_file('.job-runtime/config/linked.txt',self.workspace)

        _hidden,hidden_relative=self.private_prompt('.nested/proof.txt')
        with self.assertRaisesRegex(ConfigError,'PROMPT_INVALID'):
            prompt_file(hidden_relative,self.workspace)
        other=self.workspace/'.other'; other.mkdir(mode=0o700)
        (other/'proof.txt').write_text('prompt')
        with self.assertRaisesRegex(ConfigError,'PROMPT_INVALID'):
            prompt_file('.other/proof.txt',self.workspace)
        for rejected in ('../prompt.md',str(self.prompt.resolve()),
                         '.job-runtime/other/proof.txt', 'runtime/proof.txt',
                         'private/proof.txt','desk-private/proof.txt'):
            with self.subTest(rejected=rejected), \
                    self.assertRaisesRegex(ConfigError,'PROMPT_INVALID'):
                prompt_file(rejected,self.workspace)

    def test_valid_v1_admission_preserves_exact_config_and_job_output(self):
        # Provider-v2 admission must not alter the accepted strict v1 working-tree
        # baseline: a valid v1 config and job retain exact business-visible shape.
        profile={'auth_home':str(self.auth),'executor':'readiness'}
        job={'id':'legacy','enabled':True,'schedule':{'kind':'interval','seconds':60},
             'replay_safe':True,'model_profile':'primary','prompt_file':self.prompt_relative,
             'adapter':'legacy_adapter:prepare','adapter_config':{'mode':'synthetic'},
             'completion_adapter':'legacy_adapter:complete'}
        allocation={'schema_version':1,'jobs':[job]}
        (self.workspace/'allocation.json').write_text(json.dumps(allocation))
        config={'schema_version':1,'tick_seconds':1,'heartbeat_seconds':1,
                'stale_seconds':30,'max_workers':1,
                'retry':{'max_attempts':1,'initial_delay_seconds':1,'max_delay_seconds':1},
                'model_profiles':{'primary':profile},'allocation_files':['allocation.json'],
                'source_paths':[]}
        path=self.state/'config.json'; path.write_text(json.dumps(config)); path.chmod(0o600)
        loaded,jobs=load(path,self.workspace)
        self.assertEqual(loaded,config)
        self.assertEqual(jobs,[job])


if __name__ == '__main__': unittest.main()
