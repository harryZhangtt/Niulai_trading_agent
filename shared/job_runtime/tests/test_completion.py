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
        verify=lambda *_:{'verified':verified,'receipt':{'evidence':'synthetic-only'}}
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

    def test_completion_result_requires_exact_boolean_and_bounded_public_schema(self):
        base={'status':'succeeded','receipt':{}}
        invalid=(
            {'code':'OK'},
            {'receipt':{}},
            {'code':'OK','receipt':{}},
            {'verified':'yes'},
            {'verified':1},
            {'verified':True,'private':'secret'},
            {'verified':True,'code':'lowercase'},
            {'verified':True,'receipt':{'blob':'x'*(service._MAX_ADAPTER_RECEIPT+1)}},
        )
        for candidate in invalid:
            with self.subTest(candidate=list(candidate)):
                verify=lambda *_, candidate=candidate:candidate
                with patch.object(service,'run_business',return_value=base), \
                     patch.object(service,'adapter_module',return_value=types.SimpleNamespace(verify=verify)):
                    outcome=service.dispatcher(self.config,self.root)(self.job,self.context)
                self.assertEqual(outcome['status'],'failed')
                self.assertEqual(outcome['code'],'BUSINESS_POSTCONDITION_INVALID')
                self.assertNotIn('secret',str(outcome))

    def test_completion_receipt_rejects_deep_and_cyclic_data_without_recursion(self):
        deep={};cursor=deep
        for _ in range(1500):
            child={};cursor['child']=child;cursor=child
        cyclic={};cyclic['self']=cyclic
        for receipt in (deep,cyclic):
            verify=lambda *_,receipt=receipt:{'verified':True,'receipt':receipt}
            with patch.object(service,'run_business',return_value={'status':'succeeded','receipt':{}}), \
                 patch.object(service,'adapter_module',return_value=types.SimpleNamespace(verify=verify)):
                outcome=service.dispatcher(self.config,self.root)(self.job,self.context)
            self.assertEqual(outcome['code'],'BUSINESS_POSTCONDITION_INVALID')

    def test_completion_result_is_detached_json_and_legacy_false_remains_failure(self):
        receipt={'readback':{'id':'synthetic'}}
        candidate={'verified':True,'code':'READBACK_VERIFIED','receipt':receipt}
        with patch.object(service,'run_business',return_value={'status':'succeeded','receipt':{}}), \
             patch.object(service,'adapter_module',return_value=types.SimpleNamespace(verify=lambda *_:candidate)):
            outcome=service.dispatcher(self.config,self.root)(self.job,self.context)
        receipt['readback']['id']='mutated'
        self.assertEqual(outcome['receipt']['postcondition'],{
            'verified':True,'code':'READBACK_VERIFIED','receipt':{'readback':{'id':'synthetic'}}})
        out,_=self.run_result({'status':'succeeded','receipt':{}},False)
        self.assertEqual(out['code'],'BUSINESS_POSTCONDITION_FAILED')

    def test_model_authored_delivery_fields_never_replace_host_readback(self):
        result={'status':'succeeded','receipt':{'final':{
            'status':'sent','delivery_verified':True,'gmail_verified':True,
            'message_id':'abcdef1234567890','email_message_id':'ABCDEF1234567890',
            'send_event_id':'send-event-0001','read_event_id':'read-event-0001',
            'recipient_sha256':'a'*64,'subject_sha256':'b'*64,'body_sha256':'c'*64,
            'raw_readback_sha256':'d'*64,'readback_verified_at':'2026-11-05T08:09:10+00:00'}}}
        job={key:value for key,value in self.job.items() if key!='completion_adapter'}
        with patch.object(service,'run_business',return_value=result):
            outcome=service.dispatcher(self.config,self.root)(job,self.context)
        self.assertEqual(outcome['status'],'failed')
        self.assertEqual(outcome['code'],'BUSINESS_DELIVERY_NOT_VERIFIED')

if __name__=='__main__':unittest.main()
