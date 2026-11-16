import json,os,tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shared.job_runtime import allocation,bootstrap,setup
from shared.job_runtime.host_deploy import materialize

class OperatorSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();state=self.root/'.job-runtime';(state/'.venv/bin').mkdir(parents=True,mode=0o700)
        python=state/'.venv/bin/python';python.write_text('synthetic');python.chmod(0o700)
        requirements=self.root/'shared/job_runtime';requirements.mkdir(parents=True)
        (requirements/'bootstrap-requirements.txt').write_text('uv==0.13.6\n')
        (requirements/'claude-requirements.txt').write_text('claude-agent-sdk==0.2.179\n')
    def test_claude_is_primary_schema2_setup_and_repeat_preserves_bytes(self):
        first=setup.prepare(self.root)
        self.assertEqual((first['provider'],first['runtime_schema']),('claude_host',2))
        config=self.root/'.job-runtime/config/runtime.json';before=config.read_bytes()
        second=setup.prepare(self.root)
        self.assertFalse(second['configuration_created']);self.assertEqual(config.read_bytes(),before)
        self.assertFalse(first['services_started']);self.assertFalse(first['auth_present'])
        profile=json.loads(config.read_text())['model_profiles']['default']
        self.assertEqual(profile['model'],'claude-opus-5-5');self.assertEqual(profile['provider'],'claude_host')
    def test_atomic_add_and_enable_never_open_database(self):
        setup.prepare(self.root)
        state=self.root/'.job-runtime';config=state/'config/runtime.json';prompt=state/'config/prompts/task.txt';prompt.write_text('bounded');prompt.chmod(0o600)
        job={'id':'claude.once.1','enabled':True,'schedule':{'kind':'once','at':'2030-01-01T00:00:00+00:00','grace_seconds':300},'model_profile':'default','prompt_file':'.job-runtime/config/prompts/task.txt','replay_contract':{'version':1,'effect':'none','automatic_phases':['not_started','connecting'],'slot_operation_scope':'claude/once/1','reconciliation_adapter':None}}
        target=state/'config/jobs-v2.json';added=allocation.add_job(self.root,config,target,job)
        self.assertTrue(added['reload_required']);self.assertFalse(allocation.list_jobs(self.root,config)[0]['enabled'])
        enabled=allocation.set_enabled(self.root,config,'claude.once.1',True);self.assertTrue(enabled['reload_required'])
        self.assertTrue(allocation.list_jobs(self.root,config)[0]['enabled'])
        self.assertFalse((state/'engine/schedule.sqlite').exists())
        self.assertEqual(allocation.validate_all(self.root,config)['jobs'],1)
    def test_host_materializer_copies_no_credentials_or_links(self):
        setup.prepare(self.root)
        external=Path(self.temp.name)/'external-host'
        receipt=materialize(self.root,external_root=external)
        self.assertEqual(receipt['provider'],'claude_host');self.assertFalse(receipt['credentials_copied']);self.assertFalse(receipt['persistent_links'])
        deployed=external/'workspace';self.assertTrue((deployed/'shared/job_runtime/service.py').is_file())
        self.assertFalse((deployed/'.job-runtime/claude-home/auth.json').exists())
        self.assertTrue(receipt['service_label'].startswith('com.local.trading-agent.job-runtime.'))
    def test_bootstrap_uses_workspace_local_commands_and_receipt(self):
        bootroot=self.root/'bootstrap-workspace';requirements=bootroot/'shared/job_runtime';requirements.mkdir(parents=True);(requirements/'bootstrap-requirements.txt').write_text('uv==0.13.6\n');(requirements/'claude-requirements.txt').write_text('claude-agent-sdk==0.2.179\n')
        calls=[]
        def fake(command,*,env,timeout=600):
            calls.append(command)
            if command[1:3]==['-m','venv']:
                path=Path(command[-1]);(path/'bin').mkdir(parents=True);(path/'bin/python').write_text('py')
            elif '-m' in command and 'pip' in command:
                uv=bootroot/'.job-runtime/bootstrap/bin/uv';uv.write_text('uv');uv.chmod(0o700)
            elif command[1:3]==['venv','--python']:
                path=Path(command[-1]);(path/'bin').mkdir(parents=True,exist_ok=True);(path/'bin/python').write_text('python312');(path/'bin/python').chmod(0o700)
            return SimpleNamespace(returncode=0,stdout=('uv 0.13.6\n' if '--version' in command and 'uv' in command[0] else 'Python 3.12.16\n' if '--version' in command else ''),stderr='')
        with patch.object(bootstrap,'_run',fake):result=bootstrap.install(bootroot)
        self.assertEqual(result['python_version'],'Python 3.12.16')
        self.assertTrue((bootroot/'.job-runtime/setup/dependencies.json').is_file())
        self.assertTrue(all(str(bootroot/'.job-runtime') in ' '.join(call) or call[0].endswith('python') for call in calls))

    def test_host_materializer_rejects_traversal_and_stale_deployment(self):
        setup.prepare(self.root)
        config=self.root/'.job-runtime/config/runtime.json';value=json.loads(config.read_text());value['allocation_files']=['../../outside.json'];config.write_text(json.dumps(value));config.chmod(0o600)
        with self.assertRaises(Exception):materialize(self.root,external_root=Path(self.temp.name)/'traversal')
        # Restore a valid config and prove an existing deployment is revalidated.
        config.unlink();setup.prepare(self.root)
        external=Path(self.temp.name)/'stale';materialize(self.root,external_root=external)
        deployed=external/'workspace/shared/job_runtime/service.py';deployed.write_text(deployed.read_text()+'\n# drift\n');deployed.chmod(0o600)
        with self.assertRaisesRegex(Exception,'HOST_DEPLOY_STALE'):materialize(self.root,external_root=external)

    def test_host_materializer_keeps_mixed_provider_auth_homes_separate(self):
        setup.prepare(self.root)
        config=self.root/'.job-runtime/config/runtime.json';value=json.loads(config.read_text());state=self.root/'.job-runtime';(state/'codex-home').mkdir(exist_ok=True,mode=0o700)
        value['model_profiles']['codex']={'provider':'codex_cli','codex_bin':'/bin/true','model':'gpt-test','effort':'low','timeout_seconds':10,'auth_home':str(state/'codex-home'),'circuit':{'failure_threshold':1,'open_seconds':30,'probe_seconds':5}}
        config.write_text(json.dumps(value));config.chmod(0o600)
        external=Path(self.temp.name)/'mixed';receipt=materialize(self.root,external_root=external)
        self.assertEqual(receipt['provider'],'mixed')
        deployed=json.loads((external/'workspace/.job-runtime/config/runtime.json').read_text())
        self.assertTrue(deployed['model_profiles']['default']['auth_home'].endswith('claude-home'))
        self.assertTrue(deployed['model_profiles']['codex']['auth_home'].endswith('codex-home'))

    def test_bootstrap_rejects_replaced_interpreter_and_malformed_receipt(self):
        bootroot=self.root/'bootstrap-invalid';requirements=bootroot/'shared/job_runtime';requirements.mkdir(parents=True);(requirements/'bootstrap-requirements.txt').write_text('uv==0.13.6\n');(requirements/'claude-requirements.txt').write_text('claude-agent-sdk==0.2.179\n')
        calls=[]
        def fake(command,*,env,timeout=600):
            calls.append(command)
            if command[1:3]==['-m','venv']:
                path=Path(command[-1]);(path/'bin').mkdir(parents=True);(path/'bin/python').write_text('py')
            elif '-m' in command and 'pip' in command:
                uv=bootroot/'.job-runtime/bootstrap/bin/uv';uv.write_text('uv');uv.chmod(0o700)
            elif command[1:3]==['venv','--python']:
                path=Path(command[-1]);(path/'bin').mkdir(parents=True,exist_ok=True);(path/'bin/python').write_text('python312');(path/'bin/python').chmod(0o700)
            return SimpleNamespace(returncode=0,stdout=('uv 0.13.6\n' if command[-1]=='--version' and 'uv' in command[0] else 'Python 3.12.16\n' if '--version' in command else ''),stderr='')
        with patch.object(bootstrap,'_run',fake):bootstrap.install(bootroot)
        python=bootroot/'.job-runtime/.venv/bin/python';python.write_text('replaced');python.chmod(0o700)
        self.assertEqual(bootstrap.inspect(bootroot)['status'],'invalid')
        with patch.object(bootstrap,'_run',fake),self.assertRaisesRegex(Exception,'BOOTSTRAP_STATE_INVALID'):bootstrap.install(bootroot)

if __name__=='__main__':unittest.main()
