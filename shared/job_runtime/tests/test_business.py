"""Memory-only business subprocess tests; synthetic executable and auth only."""
from pathlib import Path
import json
import tempfile
import threading
import unittest

from shared.job_runtime.business import GMAIL,SITES,run_business

ROOT=Path(__file__).resolve().parents[3]
TEMP=ROOT/'.job-runtime/tests';TEMP.mkdir(parents=True,exist_ok=True)


class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=TEMP);self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.home=self.base/'auth';self.home.mkdir(mode=0o700)
        auth=self.home/'auth.json';auth.write_text('{"synthetic":true}');auth.chmod(0o600)
        self.binary=self.base/'fake-codex'
        self.profile={'codex_bin':str(self.binary),'model':'gpt-6.1-sol','effort':'low',
                      'timeout_seconds':3,'auth_home':str(self.home),'phase':'catalog',
                      'apps':[GMAIL,SITES],'shell':False}

    def fake(self,extra='',final=None):
        if final is None:final={'gmail_tool_names':['gmail_get_profile'],'sites_tool_names':['sites_get_site'],'catalog_verified':False}
        code='#!/usr/bin/python3\nimport sys,json,time\nfrom pathlib import Path\n'
        code+='prompt=sys.stdin.read()\n'+extra+'\n'
        code+='print(json.dumps({"type":"thread.started","thread_id":"synthetic-thread"}))\n'
        code+='print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":'+repr(json.dumps(final))+'}}))\n'
        code+='print(json.dumps({"type":"turn.completed","usage":{"input_tokens":4,"output_tokens":3}}))\n'
        self.binary.write_text(code);self.binary.chmod(0o700)

    def run_probe(self):return run_business(self.profile,'synthetic catalog only',ROOT,self.base/'run')

    def test_raw_tool_results_and_stderr_are_not_persisted(self):
        self.fake('print(json.dumps({"type":"item.completed","item":{"type":"mcp_tool_call","tool":"metadata_search","result":"SYNTHETIC_RAW_SECRET"}}));print("SYNTHETIC_STDERR_SECRET",file=sys.stderr)')
        result=self.run_probe();self.assertEqual(result['status'],'succeeded')
        self.assertNotIn('SECRET',json.dumps(result))
        for p in (self.base/'run').rglob('*'):
            if p.is_file():self.assertNotIn(b'SYNTHETIC',p.read_bytes())
        self.assertFalse((self.base/'run/events.jsonl').exists())
        self.assertFalse((self.base/'run/prompt.txt').exists())

    def test_catalog_may_not_invoke_gmail_or_sites(self):
        self.fake('print(json.dumps({"type":"item.completed","item":{"type":"mcp_tool_call","tool":"gmail_get_profile","result":"not retained"}}))')
        self.assertEqual(self.run_probe()['code'],'CATALOG_CONNECTOR_CALL_REJECTED')

    def test_candidate_flags_only_enable_selected_apps(self):
        self.fake('args=sys.argv[1:];assert "apps._default.enabled=false" in args;assert "features.shell_tool=false" in args;assert "--output-last-message" not in args;assert "--cd" in args;assert str(Path.cwd()).endswith("/work");assert "features.apps=true" in args')
        self.assertEqual(self.run_probe()['status'],'succeeded')

    def test_final_must_not_expose_bearers_or_extra_fields(self):
        self.fake(final={'status':'ok','code':'bearer SYNTHETIC_TOKEN'})
        self.assertEqual(self.run_probe()['code'],'BUSINESS_FINAL_REJECTED')
        self.fake(final={'credentials':'SYNTHETIC'})
        result=run_business(self.profile,'synthetic',ROOT,self.base/'second')
        self.assertEqual(result['code'],'BUSINESS_FINAL_FIELDS_REJECTED')

    def test_unknown_apps_and_shell_expansion_rejected(self):
        self.fake();self.profile['apps'].append('unknown-app')
        self.assertEqual(self.run_probe()['code'],'BUSINESS_APPS_POLICY_INVALID')
        self.profile['apps']=[GMAIL];self.profile['shell']=True
        self.assertEqual(self.run_probe()['code'],'BUSINESS_SHELL_POLICY_MISMATCH')

    def test_timeout_and_output_limit_are_bounded(self):
        self.fake('time.sleep(60)');self.profile['timeout_seconds']=.5
        self.assertEqual(self.run_probe()['code'],'BUSINESS_DEADLINE_EXCEEDED')
        self.fake('print("x"*5000)');self.profile['max_output_bytes']=1024;self.profile['timeout_seconds']=3
        result=run_business(self.profile,'synthetic',ROOT,self.base/'second')
        self.assertEqual(result['code'],'BUSINESS_OUTPUT_LIMIT_EXCEEDED')

    def test_cancel_before_start_has_no_child_or_run_directory(self):
        self.fake();cancel=threading.Event();cancel.set()
        result=run_business(self.profile,'synthetic',ROOT,self.base/'run',{'cancel_event':cancel})
        self.assertEqual(result['code'],'BUSINESS_CANCELLED_BEFORE_START')
        self.assertFalse((self.base/'run').exists())


    def test_automatic_review_is_explicit_business_only_and_no_sandbox_conflict(self):
        self.profile.update(phase='business',shell=True,approval_mode='automatic_review')
        self.fake('args=sys.argv[1:];assert "--approve-for-me" in args;assert "--sandbox" not in args;assert not any(x.startswith("approval_policy=") for x in args);assert \'approvals_reviewer="auto_review"\' in args',
                  final={'status':'verified','code':'SYNTHETIC_REVIEW_MODE'})
        self.assertEqual(self.run_probe()['status'],'succeeded')
        self.profile.update(phase='catalog',shell=False)
        result=run_business(self.profile,'synthetic',ROOT,self.base/'second')
        self.assertEqual(result['code'],'BUSINESS_APPROVAL_MODE_INVALID')

    def test_actual_host_approval_error_is_sanitized_and_not_a_success(self):
        value={'isError':True,'content':[{'type':'text','text':'Tool call requires approval, but approval_policy is set to never. SYNTHETIC_RAW_SECRET'}]}
        event={'type':'item.completed','item':{'type':'mcp_tool_call','tool':'gmail_send_email','result':value}}
        self.fake('print('+repr(json.dumps(event))+')',final={'status':'blocked','code':'MODEL_SELF_REPORT_ONLY'})
        result=self.run_probe()
        self.assertEqual(result['code'],'TOOL_APPROVAL_REQUIRED_POLICY_NEVER')
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['receipt']['tool_failures'],[{'tool':'gmail_send_email','code':'TOOL_APPROVAL_REQUIRED_POLICY_NEVER','dispatch_status':'rejected_before_dispatch'}])
        self.assertNotIn('SYNTHETIC_RAW_SECRET',json.dumps(result))

    def test_model_blocked_statement_is_not_proof_of_predispatch_rejection(self):
        self.fake(final={'status':'blocked','code':'GMAIL_SEND_APPROVAL_REQUIRED_POLICY_NEVER'})
        result=self.run_probe()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['receipt']['tool_failures'],[])
        self.assertNotIn('summary_parse_failure',result['receipt'])

    def test_summary_enum_failure_identifies_only_fixed_field_and_stays_failed(self):
        self.profile.update(phase='business',shell=True)
        self.fake(final={'status':'completed','price_status':'SYNTHETIC_UNSUPPORTED_ENUM'})
        result=self.run_probe()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['code'],'BUSINESS_FINAL_PRICE_STATUS_INVALID')
        self.assertEqual(result['receipt']['summary_parse_failure'],{
            'code':'BUSINESS_FINAL_PRICE_STATUS_INVALID','field':'price_status','category':'format'})
        self.assertNotIn('SYNTHETIC_UNSUPPORTED_ENUM',json.dumps(result))
        self.assertTrue(result['receipt']['turn_completed'])
        self.assertEqual(result['receipt']['exit_code'],0)

    def test_summary_security_rejections_are_not_benign_format_errors(self):
        cases=[({'status':'ok','code':'bearer SYNTHETIC_TOKEN'},'sensitive_output'),
               ({'unknown_private_field':'do not retain'},'rejected_fields')]
        for number,(final,category) in enumerate(cases):
            self.fake(final=final)
            result=run_business(self.profile,'synthetic',ROOT,self.base/('case'+str(number)))
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['receipt']['summary_parse_failure']['category'],category)
            self.assertNotIn('SYNTHETIC_TOKEN',json.dumps(result))

    def test_tool_rejection_is_never_a_summary_parse_failure(self):
        value={'isError':True,'content':[{'text':'Tool call requires approval, but approval_policy is never.'}]}
        event={'type':'item.completed','item':{'type':'mcp_tool_call','tool':'gmail_send_email','result':value}}
        self.fake('print('+repr(json.dumps(event))+')',final={'status':'BAD_ENUM'})
        result=self.run_probe()
        self.assertEqual(result['code'],'TOOL_APPROVAL_REQUIRED_POLICY_NEVER')
        self.assertNotIn('summary_parse_failure',result['receipt'])

    def test_denial_words_in_successful_tool_data_are_not_predispatch_evidence(self):
        event={'type':'item.completed','item':{'type':'mcp_tool_call','tool':'metadata_search','result':{
            'isError':False,'content':[{'type':'text','text':'Documentation: Tool requires approval with approval_policy never.'}]}}}
        self.fake('print('+repr(json.dumps(event))+')')
        self.assertEqual(self.run_probe()['receipt']['tool_failures'],[])

    def test_explicit_private_writable_root_replaces_niulai_default(self):
        calculation=self.base/'calculation';calculation.mkdir(mode=0o700)
        relative=str(calculation.relative_to(ROOT))
        self.profile.update(phase='business',shell=True,writable_roots=[relative])
        self.fake('args=sys.argv[1:];grants=[args[i+1] for i,x in enumerate(args) if x=="--add-dir"];assert grants=='+repr([str(calculation)])+';Path('+repr(str(calculation/'proof.txt'))+').write_text("synthetic")',
                  final={'status':'ok','code':'SYNTHETIC_ROOT_CHECK'})
        result=self.run_probe()
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(result['receipt']['writable_roots'],[relative])
        self.assertEqual((calculation/'proof.txt').read_text(),'synthetic')

    def test_absent_writable_roots_preserves_niulai_default(self):
        self.profile.update(phase='business',shell=True)
        self.fake('args=sys.argv[1:];grants=[args[i+1] for i,x in enumerate(args) if x=="--add-dir"];assert grants=='+repr([str(ROOT/'.niulai-state')]),
                  final={'status':'ok','code':'SYNTHETIC_DEFAULT_CHECK'})
        result=self.run_probe()
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(result['receipt']['writable_roots'],['.niulai-state'])

    def test_source_absolute_traversal_and_missing_roots_fail_before_launch(self):
        self.fake();self.profile.update(phase='business',shell=True)
        cases=[('.', 'BUSINESS_WRITABLE_ROOT_REJECTED'),
               ('shared/job_runtime','BUSINESS_WRITABLE_ROOT_REJECTED'),
               (str(self.base),'BUSINESS_WRITABLE_ROOT_REJECTED'),
               ('.job-runtime/../niulai-private','BUSINESS_WRITABLE_ROOT_REJECTED'),
               (str((self.base/'missing').relative_to(ROOT)),'BUSINESS_WRITABLE_ROOT_MISSING')]
        for index,(root,code) in enumerate(cases):
            self.profile['writable_roots']=[root]
            run=self.base/('rejected'+str(index))
            result=run_business(self.profile,'synthetic',ROOT,run)
            self.assertEqual(result['code'],code)
            self.assertFalse(run.exists())

    def test_auth_ancestor_and_descendant_grants_are_rejected(self):
        self.fake();self.profile.update(phase='business',shell=True)
        child=self.home/'private-child';child.mkdir(mode=0o700)
        for index,root in enumerate((self.base,self.home,child)):
            self.profile['writable_roots']=[str(root.relative_to(ROOT))]
            run=self.base/('auth-rejected'+str(index))
            result=run_business(self.profile,'synthetic',ROOT,run)
            self.assertEqual(result['code'],'BUSINESS_WRITABLE_AUTH_OVERLAP')
            self.assertFalse(run.exists())

    def test_symlink_and_duplicate_grants_are_rejected(self):
        self.fake();self.profile.update(phase='business',shell=True)
        target=self.base/'calculation';target.mkdir(mode=0o700)
        link=self.base/'linked';link.symlink_to(target,target_is_directory=True)
        self.profile['writable_roots']=[str(link.relative_to(ROOT))]
        self.assertEqual(self.run_probe()['code'],'BUSINESS_WRITABLE_ROOT_SYMLINK')
        relative=str(target.relative_to(ROOT))
        self.profile['writable_roots']=[relative,relative]
        self.assertEqual(self.run_probe()['code'],'BUSINESS_WRITABLE_ROOTS_INVALID')

    def test_catalog_or_job_context_cannot_expand_writable_roots(self):
        self.fake();self.profile['writable_roots']=[]
        self.assertEqual(self.run_probe()['code'],'BUSINESS_WRITABLE_ROOTS_INVALID')
        self.profile.update(phase='business',shell=True,writable_roots=[])
        result=run_business(self.profile,'synthetic',ROOT,self.base/'run',
                            {'writable_roots':['shared/job_runtime']})
        self.assertEqual(result['code'],'BUSINESS_CONTEXT_INVALID')
        self.assertFalse((self.base/'run').exists())


if __name__=='__main__':unittest.main()
