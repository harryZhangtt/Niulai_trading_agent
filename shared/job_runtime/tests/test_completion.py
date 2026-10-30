"""An actual business postcondition outranks only a harmless summary-format error."""
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from shared.job_runtime import service

ROOT=Path(__file__).resolve().parents[3]

class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.job-runtime/tests');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'prompt.txt').write_text('Synthetic test')
        self.config={'source_paths':[],'model_profiles':{'b':{'executor':'business','phase':'business'}}}
        self.job={'model_profile':'b','prompt_file':'prompt.txt','completion_adapter':'synthetic:verify'}
        self.context={'attempt_id':'synthetic-attempt'}
        service.STOP.clear()

    def run_result(self,result,verified):
        verify=lambda *_:{'verified':verified,'evidence':'synthetic-only'}
        with patch.object(service,'run_business',return_value=result),patch.object(service,'adapter_module',return_value=types.SimpleNamespace(verify=verify)) as module:
            outcome=service.dispatcher(self.config,self.root)(self.job,self.context)
            return outcome,module.call_count

    def test_formatting_failure_needs_completed_transport_and_business_evidence(self):
        value={'status':'failed','code':'BUSINESS_FINAL_PRICE_STATUS_INVALID','receipt':{'turn_completed':True,'exit_code':0,'tool_failures':[], 'summary_parse_failure':{'category':'format'}}}
        out,calls=self.run_result(value,True)
        self.assertEqual(out['status'],'succeeded');self.assertEqual(out['code'],'BUSINESS_POSTCONDITION_VERIFIED');self.assertEqual(calls,1)
        self.assertIn('summary_parse_failure',out['receipt'])
        out,_=self.run_result(value,False);self.assertEqual(out['status'],'failed')

    def test_security_rejection_and_approval_denial_never_use_format_fallback(self):
        for category in ('sensitive_output','rejected_fields','boundary_violation'):
            out,calls=self.run_result({'status':'failed','code':'REJECTED','receipt':{'turn_completed':True,'exit_code':0,'summary_parse_failure':{'category':category}}},True)
            self.assertEqual(out['status'],'failed');self.assertEqual(calls,0)
        out,calls=self.run_result({'status':'failed','code':'APPROVAL_REQUIRED','receipt':{'turn_completed':True,'exit_code':0,'tool_failures':[{'code':'APPROVAL_REQUIRED'}],'summary_parse_failure':{'category':'format'}}},True)
        self.assertEqual(out['status'],'failed');self.assertEqual(calls,0)

    def test_model_success_without_postcondition_is_not_delivery_success(self):
        out,calls=self.run_result({'status':'succeeded','receipt':{'final':{'status':'sent','delivery_verified':True,'message_id':'synthetic'}}},False)
        self.assertEqual(out['status'],'failed');self.assertEqual(calls,1)

if __name__=='__main__':unittest.main()
