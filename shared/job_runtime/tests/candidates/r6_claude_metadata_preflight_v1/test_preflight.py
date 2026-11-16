from __future__ import annotations
import base64, dataclasses, inspect, json, os, pathlib, shutil, stat, sys, tempfile, unittest
from datetime import datetime, timezone
from unittest import mock
ROOT=pathlib.Path(__file__).resolve().parents[5]; sys.path.insert(0,str(ROOT))
import shared.job_runtime.candidates.r6_claude_metadata_preflight_v1 as package
from shared.job_runtime.candidates.r6_claude_metadata_preflight_v1 import constants as C
from shared.job_runtime.candidates.r6_claude_metadata_preflight_v1 import engine
from shared.job_runtime.candidates.r6_claude_metadata_preflight_v1.contracts import ContractError
from shared.job_runtime.candidates.r6_claude_metadata_preflight_v1.custody import AtomicWriteError,_write_all
FIXTURE=pathlib.Path(__file__).parent/'fixtures'/'fake_claude'
STATUS='DISABLED_PROVIDER_FREE_PENDING_CLAUDE_V8_P0_V10_GRANTS_AND_FRESH_REVIEW'

class Clock:
    def __init__(self): self.value=datetime(2026,11,13,12,0,tzinfo=timezone.utc)
    def __call__(self): return self.value

class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name).resolve(); self.auth=self.root/'auth'; self.review=self.root/'review'; self.catalog=self.root/'catalog'
        for path in (self.auth,self.review,self.catalog): path.mkdir(mode=0o700)
        self.clock=Clock()
    def runtime(self,scenario='ready',binary=FIXTURE,**kw): return engine._runtime_for_test(binary,self.auth,self.review,self.catalog,self.clock,scenario=scenario,**kw)
    def auth_ready(self,scenario='ready'):
        runtime=self.runtime(scenario); receipt=engine._run_auth_for_test(runtime); review=engine._install_clean_test_review(runtime)
        return runtime,receipt,review

class PublicBoundaryTests(unittest.TestCase):
    def test_public_api_is_two_zero_argument_disabled_entrypoints(self):
        self.assertEqual(package.__all__,['auth_readiness','catalog_readiness'])
        public={n:v for n,v in vars(package).items() if not n.startswith('_') and callable(v)}
        self.assertEqual(public,{'auth_readiness':package.auth_readiness,'catalog_readiness':package.catalog_readiness})
        for fn in public.values():
            self.assertEqual(list(inspect.signature(fn).parameters),[])
            with self.assertRaises(TypeError): fn('/tmp/caller-root')
            for key in ('root','clock','model','command','provider'):
                with self.assertRaises(TypeError): fn(**{key:object()})
            value=fn(); self.assertEqual(value['status'],STATUS); self.assertFalse(value['activation']); self.assertFalse(value['registered']); self.assertTrue(all(v==0 for v in value['effects'].values()))
    def test_private_seams_not_exported(self):
        self.assertFalse(any(name.startswith('_run_') for name in package.__all__))
        source=(pathlib.Path(package.__file__).parent/'public.py').read_text().lower()
        for forbidden in ('subprocess','socket','anthropic','claude-agent-sdk'): self.assertNotIn(forbidden,source)

class AuthorityTests(RuntimeCase):
    def test_caller_cannot_supply_authority_or_review(self):
        with self.assertRaises(TypeError): engine._runtime_for_test(FIXTURE,self.auth,self.review,self.catalog,self.clock,authority=object())
        runtime,_,_=self.auth_ready()
        with self.assertRaises(TypeError): engine._run_catalog_for_test(runtime,{'verdict':'CLEAN'})
    def test_registry_pin_drift_fails_before_process(self):
        runtime=self.runtime(); runner=mock.Mock(side_effect=AssertionError('provider boundary')); runtime=dataclasses.replace(runtime,runner=runner)
        bad=dataclasses.replace(engine._REGISTRY,sha256='0'*64)
        with mock.patch.object(engine,'_REGISTRY',bad):
            with self.assertRaises(engine.LocalPreflightError): engine._run_auth_for_test(runtime)
        runner.assert_not_called(); self.assertEqual(list(self.auth.iterdir()),[])
    def test_review_is_committed_exact_and_tamper_rejected(self):
        runtime,auth,review=self.auth_ready(); self.assertEqual(review['receipt_sha256'],engine.sha256_bytes(engine.canonical_bytes(auth)))
        path=self.review/'review.json'; value=json.loads(path.read_text()); value['verdict']='CLEAN'; path.write_text(json.dumps(value))
        with self.assertRaises(engine.LocalPreflightError): engine._run_catalog_for_test(runtime)
        self.assertEqual(list(self.catalog.iterdir()),[])

class AuthOperationTests(RuntimeCase):
    def test_ready_receipt_sanitized_and_raw_private(self):
        _,receipt,_=self.auth_ready(); self.assertEqual(receipt['status'],'READY')
        public=json.dumps(receipt,sort_keys=True); self.assertNotIn('private-fixture',public); self.assertNotIn('synthetic-secret',public)
        raw=json.loads((self.auth/'raw.json').read_text()); decoded=base64.b64decode(raw['stdout_base64']).decode(); self.assertIn('synthetic-secret-must-redact',decoded)
        for name in ('started.json','raw.json','receipt.json','commit.json'): self.assertEqual(stat.S_IMODE(os.lstat(self.auth/name).st_mode),0o600)
        self.assertEqual(receipt['request_accounting'],{'auth_status_reads':1,'catalog_requests':0,'inference':0,'attempts':1,'retries':0,'replays':0,'status_after_unknown':0,'second_request':0,'concurrency':1})
    def test_not_ready(self): self.assertEqual(engine._run_auth_for_test(self.runtime('not_ready'))['status'],'NOT_READY')
    def test_timeout_unknown_and_second_fenced(self):
        runtime=self.runtime('timeout')
        with mock.patch.object(C,'AUTH_TIMEOUT_SECONDS',0.05): first=engine._run_auth_for_test(runtime)
        self.assertEqual(first['status'],'UNKNOWN'); runner=mock.Mock(side_effect=AssertionError('second execution'))
        with self.assertRaises(engine.PreviousOutcomeUnknown): engine._run_auth_for_test(dataclasses.replace(runtime,runner=runner))
        runner.assert_not_called()
    def test_nonzero_and_malformed_unknown(self):
        for scenario in ('nonzero','malformed'):
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as td:
                    local=pathlib.Path(td).resolve(); roots=[local/n for n in ('a','r','c')]
                    for path in roots:path.mkdir(mode=0o700)
                    runtime=engine._runtime_for_test(FIXTURE,*roots,self.clock,scenario=scenario)
                    self.assertEqual(engine._run_auth_for_test(runtime)['status'],'UNKNOWN')
    def test_binary_and_source_pin_drift_before_process(self):
        for runtime,patcher in ((self.runtime(binary_sha_override='0'*64),mock.patch.object(C,'MODEL',C.MODEL)),(self.runtime(),mock.patch.object(C,'DECISION_REF',(C.DECISION_REF[0],C.DECISION_REF[1],'0'*64)))):
            runner=mock.Mock(side_effect=AssertionError('provider boundary')); runtime=dataclasses.replace(runtime,runner=runner)
            with patcher:
                with self.assertRaises(engine.LocalPreflightError): engine._run_auth_for_test(runtime)
            runner.assert_not_called(); self.assertEqual(list(self.auth.iterdir()),[])
    def test_path_swap_executes_held_fd_and_fences_identity_drift(self):
        binary=self.root/'fake-copy'; shutil.copyfile(FIXTURE,binary); binary.chmod(0o700); marker=self.root/'swapped-ran'
        runtime=self.runtime(binary=binary)
        def swapping(argv,binary_fd,out,err,timeout,env):
            replacement=self.root/'replacement'; replacement.write_text('#!/bin/sh\necho ran > "%s"\n' % marker); replacement.chmod(0o700); os.replace(replacement,binary)
            return engine._subprocess_runner(argv,binary_fd,out,err,timeout,env)
        receipt=engine._run_auth_for_test(dataclasses.replace(runtime,runner=swapping))
        self.assertEqual(receipt['status'],'READY'); self.assertFalse(marker.exists())

class CatalogOperationTests(RuntimeCase):
    def test_exact_terminal_and_assistant_duplicates_ignored(self):
        runtime,_,_=self.auth_ready(); receipt=engine._run_catalog_for_test(runtime)
        self.assertEqual(receipt['status'],'READY'); self.assertEqual(receipt['catalog_terminal'],{'authority':'sole_terminal_result','terminal_result_index':2,'display_model':'Opus 5.5','assistant_stream_ignored':True}); self.assertEqual(receipt['request_accounting']['inference'],0)
    def test_ambiguous_negative_prefix_and_missing_accounting_unknown(self):
        for scenario in ('duplicate_terminal','negated_model','prefix_model','missing_accounting','prior_usage'):
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as td:
                    local=pathlib.Path(td).resolve(); roots=[local/n for n in ('a','r','c')]
                    for path in roots:path.mkdir(mode=0o700)
                    runtime=engine._runtime_for_test(FIXTURE,*roots,self.clock,scenario='ready'); engine._run_auth_for_test(runtime); engine._install_clean_test_review(runtime)
                    env=dict(runtime.env); env['R6_FAKE_SCENARIO']=scenario; runtime=dataclasses.replace(runtime,env=env)
                    self.assertEqual(engine._run_catalog_for_test(runtime)['status'],'UNKNOWN')
    def test_nonzero_unknown_and_no_second_catalog(self):
        runtime,_,_=self.auth_ready(); env=dict(runtime.env); env['R6_FAKE_SCENARIO']='nonzero'; runtime=dataclasses.replace(runtime,env=env)
        self.assertEqual(engine._run_catalog_for_test(runtime)['status'],'UNKNOWN'); runner=mock.Mock(side_effect=AssertionError('second request'))
        with self.assertRaises(engine.PreviousOutcomeUnknown): engine._run_catalog_for_test(dataclasses.replace(runtime,runner=runner))
        runner.assert_not_called()
    def test_catalog_requires_committed_clean_fresh_auth(self):
        runtime=self.runtime(); auth=engine._run_auth_for_test(runtime)
        with self.assertRaises(FileNotFoundError): engine._run_catalog_for_test(runtime)
        self.assertEqual(list(self.catalog.iterdir()),[]); engine._install_clean_test_review(runtime)
        self.clock.value=datetime.fromisoformat(auth['fresh_until'].replace('Z','+00:00'))
        with self.assertRaises(ContractError): engine._run_catalog_for_test(runtime)
        self.assertEqual(list(self.catalog.iterdir()),[])
    def test_auth_receipt_substitution_rejected(self):
        runtime,_,_=self.auth_ready(); path=self.auth/'receipt.json'; value=json.loads(path.read_text()); value['status']='NOT_READY'; path.write_text(json.dumps(value))
        with self.assertRaises(engine.LocalPreflightError): engine._run_catalog_for_test(runtime)

class CustodyTests(RuntimeCase):
    def test_root_mode_and_symlink_rejected_before_process(self):
        os.chmod(self.auth,0o755); runtime=self.runtime(); runner=mock.Mock(side_effect=AssertionError('provider boundary')); runtime=dataclasses.replace(runtime,runner=runner)
        with self.assertRaises(Exception): engine._run_auth_for_test(runtime)
        runner.assert_not_called(); os.chmod(self.auth,0o700); real=self.root/'real'; real.mkdir(mode=0o700); link=self.root/'link'; link.symlink_to(real,target_is_directory=True)
        with self.assertRaises(OSError): engine._run_auth_for_test(dataclasses.replace(runtime,auth_root=link))
    def test_short_write_and_zero_write(self):
        path=self.root/'short'; fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
        try: _write_all(fd,b'abcdefghij',lambda target,payload:os.write(target,payload[:3])); os.lseek(fd,0,os.SEEK_SET); self.assertEqual(os.read(fd,20),b'abcdefghij')
        finally: os.close(fd)
        fd=os.open(self.root/'zero',os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with self.assertRaises(AtomicWriteError): _write_all(fd,b'x',lambda _fd,_payload:0)
        finally: os.close(fd)
    def test_second_transient_create_failure_cleans_first(self):
        runtime=self.runtime(); real=engine._create_transient; calls=[]
        def create(root,name):
            calls.append(name)
            if name=='stderr.transient': raise OSError('injected')
            return real(root,name)
        with mock.patch.object(engine,'_create_transient',side_effect=create):
            with self.assertRaises(OSError): engine._run_auth_for_test(runtime)
        self.assertFalse((self.auth/'stdout.transient').exists()); self.assertEqual(calls,['stdout.transient','stderr.transient'])
        with self.assertRaises(engine.PreviousOutcomeUnknown): engine._run_auth_for_test(runtime)
    def test_cleanup_attempts_both_transients(self):
        runtime=self.runtime(); real=engine._destroy_transient; calls=[]
        def destroy(root_fd,file_fd,name):
            calls.append(name); real(root_fd,file_fd,name)
            if name=='stdout.transient': raise OSError('injected cleanup')
        with mock.patch.object(engine,'_destroy_transient',side_effect=destroy):
            with self.assertRaises(AtomicWriteError): engine._run_auth_for_test(runtime)
        self.assertEqual(calls,['stdout.transient','stderr.transient']); self.assertFalse(any('transient' in p.name for p in self.auth.iterdir()))
    def test_no_transient_leak_on_nominal(self):
        self.auth_ready(); self.assertFalse(any('transient' in p.name for p in self.auth.iterdir())); self.assertTrue((self.auth/'commit.json').exists())

class SchemaTests(unittest.TestCase):
    def test_draft_closed_and_operation_status_coupled(self):
        directory=ROOT/'shared/job_runtime/candidates/r6_claude_metadata_preflight_v1/schemas'
        for path in directory.glob('*.schema.json'):
            value=json.loads(path.read_text()); self.assertEqual(value['$schema'],'https://json-schema.org/draft/2020-12/schema')
            def walk(node):
                if isinstance(node,dict):
                    if node.get('type')=='object': self.assertIs(node.get('additionalProperties'),False,path.name)
                    for child in node.values():walk(child)
                elif isinstance(node,list):
                    for child in node:walk(child)
            walk(value)
        auth=json.loads((directory/'auth-receipt-v1.schema.json').read_text()); cat=json.loads((directory/'catalog-receipt-v1.schema.json').read_text())
        self.assertEqual(auth['properties']['request_accounting']['properties']['auth_status_reads']['const'],1); self.assertEqual(auth['properties']['request_accounting']['properties']['catalog_requests']['const'],0)
        self.assertEqual(cat['properties']['request_accounting']['properties']['auth_status_reads']['const'],0); self.assertEqual(cat['properties']['request_accounting']['properties']['catalog_requests']['const'],1)
        self.assertEqual(len(auth['allOf']),2); self.assertEqual(len(cat['allOf']),2)

if __name__=='__main__': unittest.main()
