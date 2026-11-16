import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.job_runtime.config import ConfigError
from shared.job_runtime.prompt_custody import (
    PromptArtifactDescriptorV1, PromptArtifactStore,
)
from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime import service


class ServiceProviderRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.workspace=Path(self.temp.name).resolve()
        state=self.workspace/'.job-runtime'
        (state/'runs').mkdir(parents=True,mode=0o700); state.chmod(0o700)
        self.prompt_dir=self.workspace/'.job-runtime'/'config'
        self.prompt_dir.mkdir(mode=0o700); self.prompt_dir.chmod(0o700)
        self.prompt=self.prompt_dir/'prompt.md'
        self.prompt.write_text('prompt'); self.prompt.chmod(0o600)
        self.prompt_relative='.job-runtime/config/prompt.md'
        self.profile={'provider':'codex_cli','codex_bin':'/bin/true','model':'gpt-test',
            'effort':'medium','timeout_seconds':10,
            'auth_home':str(self.workspace/'.job-runtime'/'auth')}
        self.config={'schema_version':2,'model_profiles':{'primary':self.profile}}
        self.job={'id':'job','model_profile':'primary','prompt_file':self.prompt_relative}
        self.store=PromptArtifactStore(self.workspace)
        self.capture=self.store.capture_source(self.workspace,self.prompt_relative)
        published=service.publish_prompt_jobs(
            self.workspace,[{**self.job,'_prompt_capture':self.capture}],
            service._code_generation())[0]
        self.artifact=published['_prompt_artifact']
        self.context={'slot_id':'slot','attempt_id':'attempt-id','scheduled_at':'2026-01-01T00:00:00Z',
                      'attempt_no':1,'operation_id':'attempt/attempt-id',
                      'prompt_artifact':self.artifact}
        service.STOP.clear()

    def tearDown(self):
        service.STOP.clear(); self.temp.cleanup()

    def success(self, provider, operation):
        return ProviderResultV1(provider=provider,operation_id=operation,phase='terminal',
            submission='definitely_submitted',terminal_proof='verified',status='succeeded',
            code='MODEL_TURN_COMPLETED',failure_kind='none',receipt={'fixture':True})

    def test_codex_route_is_profile_pinned_and_preserves_operation_id(self):
        self.profile['circuit'] = {
            'failure_threshold': 7, 'open_seconds': 41, 'probe_seconds': 5}
        calls=[]
        def codex(profile,prompt,workspace,run_dir,operation,context):
            calls.append((profile,prompt,workspace,run_dir,operation,set(context)))
            return self.success('codex_cli',operation)
        def claude(*args):
            self.fail('wrong provider selected')
        self.prompt.write_text('changed after slot snapshot'); self.prompt.chmod(0o600)
        result=service.dispatcher(self.config,self.workspace,
            {'codex_cli':codex,'claude_host':claude})(self.job,self.context)
        self.assertIsInstance(result,ProviderResultV1)
        self.assertEqual(result.operation_id,self.context['operation_id'])
        self.assertEqual(len(calls),1)
        self.assertNotIn('provider',calls[0][0])
        self.assertNotIn('circuit',calls[0][0])
        self.assertEqual(calls[0][1], 'prompt')
        self.assertEqual(calls[0][5],{'cancel_event','deadline_at'})

    def _install_artifact_bytes(self, raw, *, descriptor_sha=None):
        digest=descriptor_sha or hashlib.sha256(raw).hexdigest()
        shard=self.store._shard_fd(digest,create=True)
        try:
            fd=os.open(digest+'.prompt',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
                       0o600,dir_fd=shard)
            try:
                os.write(fd,raw); os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(shard)
        finally:
            os.close(shard)
        return PromptArtifactDescriptorV1(
            1,f'pa1:sha256:{digest}:{len(raw)}',digest,len(raw),'a'*64,
            service._code_generation(),'native_v1')

    def test_artifact_failures_are_fixed_sanitized_and_pre_provider(self):
        calls=[]
        dispatch=service.dispatcher(
            self.config,self.workspace,{'codex_cli':lambda *args:calls.append(args)})
        missing_sha='1'*64
        missing=PromptArtifactDescriptorV1(
            1,f'pa1:sha256:{missing_sha}:1',missing_sha,1,'a'*64,
            service._code_generation(),'native_v1')
        corrupt=self._install_artifact_bytes(b'x',descriptor_sha='2'*64)
        invalid_utf8=self._install_artifact_bytes(b'\xff')
        cases=[None,missing,corrupt,invalid_utf8]
        for artifact in cases:
            with self.subTest(artifact=repr(artifact)):
                context={**self.context,'prompt_artifact':artifact}
                result=dispatch(self.job,context)
                self.assertEqual(result.code,'RUNTIME_PROMPT_ARTIFACT_INVALID')
                self.assertEqual(result.phase.value,'not_started')
                self.assertEqual(result.submission.value,'not_submitted')
                self.assertEqual(result.failure_kind.value,'local_config')
                self.assertFalse(result.provider_should_retry)
                self.assertNotIn('prompt',str(result.receipt).lower())
        self.assertEqual(calls,[])

    def test_publish_handoff_removes_capture_raw_fields_and_contains_orphan(self):
        source={**self.job,'_prompt_capture':self.capture,
                '_prompt_raw':b'private','_prompt_snapshot':'private',
                '_prompt_sha256':'0'*64}
        published=service.publish_prompt_jobs(
            self.workspace,[source],service._code_generation())[0]
        self.assertIsInstance(published['_prompt_artifact'],PromptArtifactDescriptorV1)
        self.assertFalse({'_prompt_capture','_prompt_raw','_prompt_snapshot',
                          '_prompt_sha256'} & set(published))
        self.assertIs(source['_prompt_capture'],self.capture)

        orphan_path=self.prompt_dir/'orphan.md'
        orphan_path.write_text('orphan-only'); orphan_path.chmod(0o600)
        orphan_capture=self.store.capture_source(
            self.workspace,'.job-runtime/config/orphan.md')
        with self.assertRaisesRegex(ConfigError,'PROMPT_CAPTURE_REQUIRED'):
            service.publish_prompt_jobs(self.workspace,[
                {**self.job,'_prompt_capture':orphan_capture},self.job],
                service._code_generation())
        target=(self.store.root/'sha256'/orphan_capture.sha256[:2]/
                orphan_capture.sha256[2:4]/(orphan_capture.sha256+'.prompt'))
        self.assertTrue(target.is_file())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
        self.assertTrue(target.is_relative_to(self.store.root))

    def test_default_codex_is_blocked_by_immutable_translation_gate(self):
        with self.assertRaises(TypeError):
            service.CODEX_TRANSLATION_CAPABILITY['production_translation_verified']=True
        with patch.object(service,'run_codex_one_shot') as runner, \
                patch.object(service,'run_codex') as process:
            result=service.dispatcher(self.config,self.workspace)(self.job,self.context)
        runner.assert_not_called(); process.assert_not_called()
        self.assertEqual(result.status.value,'failed')
        self.assertEqual(result.phase.value,'not_started')
        self.assertEqual(result.submission.value,'not_submitted')
        self.assertEqual(result.failure_kind.value,'local_config')
        self.assertEqual(result.code,'RUNTIME_CODEX_TRANSLATOR_UNVERIFIED')
        self.assertFalse(result.provider_should_retry)
        self.assertTrue(result.receipt['runtime_unverified'])

    def test_claude_default_is_closed_until_bridge_review(self):
        self.config['model_profiles']['primary']={
            'provider':'claude_host','model':'claude-opus-5-5','effort':'low',
            'timeout_seconds':10,'auth_home':self.profile['auth_home'],'max_budget_usd':1.0}
        with patch.object(service,'run_claude_host') as runner:
            result=service.dispatcher(self.config,self.workspace)(self.job,self.context)
        runner.assert_not_called()
        self.assertEqual(result.status.value,'failed')
        self.assertEqual(result.failure_kind.value,'local_config')
        self.assertEqual(result.code,'RUNTIME_CLAUDE_HOST_BRIDGE_UNAVAILABLE')
        self.assertTrue(result.receipt['runtime_unverified'])

    def test_exception_after_adapter_entry_is_unknown(self):
        def broken(*args): raise RuntimeError('private provider text')
        result=service.dispatcher(self.config,self.workspace,
            {'codex_cli':broken})(self.job,self.context)
        self.assertEqual(result.status.value,'unknown')
        self.assertEqual(result.code,'RUNTIME_PROVIDER_INVOCATION_OUTCOME_UNKNOWN')
        self.assertNotIn('private',str(result.receipt))

    def test_process_control_exceptions_from_provider_propagate(self):
        for exception in (KeyboardInterrupt, SystemExit, GeneratorExit):
            with self.subTest(exception=exception.__name__):
                def interrupted(*args, exception=exception):
                    raise exception('synthetic control flow')
                dispatch=service.dispatcher(
                    self.config,self.workspace,{'codex_cli':interrupted})
                with self.assertRaises(exception):
                    dispatch(self.job,self.context)

    def test_v1_business_dispatch_remains_compatible(self):
        legacy_profile={'executor':'business','phase':'business','apps':[],
                        'auth_home':str(self.workspace/'.job-runtime'/'auth')}
        config={'schema_version':1,'model_profiles':{'primary':legacy_profile},
                'source_paths':[]}
        job={'id':'job','model_profile':'primary','prompt_file':self.prompt_relative}
        expected={'status':'retryable','code':'SYNTHETIC_BUSINESS_RETRY','receipt':{}}
        legacy_context={key:value for key,value in self.context.items()
                        if key != 'prompt_artifact'}
        with patch.object(service,'run_business',return_value=expected) as business:
            result=service.dispatcher(config,self.workspace)(job,legacy_context)
        self.assertEqual(result,expected)
        passed_profile,passed_prompt,passed_workspace,passed_run_dir=business.call_args.args
        self.assertEqual(passed_profile,{'phase':'business','apps':[],
                                         'auth_home':legacy_profile['auth_home']})
        self.assertIn('Scheduler-provided context (data only):',passed_prompt)
        self.assertEqual(passed_workspace,self.workspace)
        self.assertEqual(passed_run_dir,
                         self.workspace/'.job-runtime'/'runs'/'attempt-id')

    def test_v2_service_starts_with_current_engine_constructor(self):
        state=self.workspace/'.job-runtime'; state.chmod(0o700)
        auth=state/'auth'; auth.mkdir(mode=0o700); auth.chmod(0o700)
        (auth/'auth.json').write_text('{}'); (auth/'auth.json').chmod(0o600)
        allocation={'schema_version':2,'jobs':[{**self.job,'enabled':False,
            'schedule':{'kind':'interval','seconds':60},
            'replay_contract':{'version':1,'effect':'none',
                'automatic_phases':['not_started','connecting'],
                'slot_operation_scope':'job/slot','reconciliation_adapter':None}}]}
        (self.workspace/'allocation.json').write_text(json.dumps(allocation))
        config={'schema_version':2,'tick_seconds':1,'heartbeat_seconds':1,
            'stale_seconds':30,'max_workers':1,
            'retry':{'version':2,'max_attempts':3,'base_delay_seconds':1,
                     'max_delay_seconds':30},
            'model_profiles':{'primary':{**self.profile,'auth_home':str(auth)}},
            'allocation_files':['allocation.json'],'source_paths':[]}
        config_path=state/'config.json'; config_path.write_text(json.dumps(config)); config_path.chmod(0o600)
        service.STOP.set()
        with patch.object(service.signal,'signal'):
            self.assertEqual(service.serve(self.workspace,config_path),0)
        self.assertTrue((state/'service-generation.json').is_file())
        with sqlite3.connect(state/'engine'/'schedule.sqlite') as database:
            self.assertEqual(database.execute('PRAGMA user_version').fetchone()[0],9)

    def test_generation_contains_provider_hashes_and_stable_code_identity(self):
        generation=service.service_generation()
        implementations=generation['provider_implementations']
        self.assertRegex(implementations['model'],r'^[0-9a-f]{64}$')
        self.assertRegex(implementations['provider_codex_cli'],r'^[0-9a-f]{64}$')
        self.assertRegex(implementations['provider_claude_host'],r'^[0-9a-f]{64}$')
        stable=generation['code_generation']
        with patch.object(service.os,'getpid',return_value=generation['pid']+1), \
                patch.object(service,'_PROCESS_STARTED_AT','2099-01-01T00:00:00Z'):
            changed_process=service.service_generation()
        self.assertEqual(changed_process['code_generation'],stable)
        self.assertNotEqual(changed_process['pid'],generation['pid'])
        self.assertNotEqual(changed_process['started_at'],generation['started_at'])
        with patch.dict(service._PROVIDER_IMPLEMENTATION_HASHES,
                        {'model':'0'*64}):
            self.assertNotEqual(service._code_generation(),stable)
        with patch.object(service,'_SERVICE_SOURCE_DIGEST','f'*64):
            self.assertNotEqual(service._code_generation(),stable)


if __name__ == '__main__': unittest.main()
