"""Focused trusted-adapter Gmail claim propagation; no model or send occurs."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from shared.job_runtime import service

ROOT=Path(__file__).resolve().parents[3]


class ServiceGmailClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.job-runtime/tests');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'prompt.txt').write_text('Synthetic prompt')
        self.config={'source_paths':[],'model_profiles':{'b':{'executor':'business','phase':'business'}}}
        self.job={'id':'job.synthetic','model_profile':'b','prompt_file':'prompt.txt','adapter':'fixture:prepare'}
        self.context={'slot_id':'slot.synthetic','attempt_id':'attempt.synthetic','scheduled_at':'2026-11-05T00:00:00+00:00'}
        self.generation={'origin':'fixture.py','source_sha256':'c'*64}
        self.service_generation={'pid':123,'started_at':'2026-11-05T00:00:00+00:00','python':{'executable':'/python','version':'3'},
                                 'service':{'protocol_version':2,'origin':'shared/job_runtime/service.py','source_sha256':'a'*64}}
        service._GMAIL_CLAIMS.clear();service.STOP.clear()
        self.attested_implementations={
            key:hashlib.sha256(path.read_bytes()).hexdigest()
            for key,path in service._IMPLEMENTATION_PATHS.items()}
        hashes=patch.dict(service._IMPLEMENTATION_HASHES,self.attested_implementations)
        hashes.start();self.addCleanup(hashes.stop)
        business=sys.modules['shared.job_runtime.business']
        identity=patch.object(business,'IMPLEMENTATION_SHA256',
                              self.attested_implementations['business'])
        identity.start();self.addCleanup(identity.stop)

    def claim(self,**changes):
        value={'schema_version':1,'job_id':self.job['id'],'slot_id':self.context['slot_id'],
               'attempt_id':self.context['attempt_id'],'host':'a'*64,
               'run':hashlib.sha256(json.dumps(self.service_generation,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
               'candidate':'c'*64,'mode':'text','delivery_payload_sha256':'d'*64,
               'recipient_sha256':'e'*64,'subject_sha256':'f'*64,'sender_identity_sha256':'1'*64,
               'profile_identity_sha256':'1'*64,'body_sha256':'2'*64}
        value.update(changes)
        value['payload_sha256']=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return value

    def dispatch(self,claim,runner=None):
        seen={}
        def prepare(options,workspace,context,runtime):
            self.assertEqual(context['job_id'],self.job['id'])
            return {'public':'value','gmail_claim':claim}
        module=types.SimpleNamespace(RUNTIME_CONTEXT_VERSION=3,prepare=prepare)
        def run(profile,prompt,workspace,run_dir,context):
            seen.update(prompt=prompt,context=context)
            service._consume_gmail_claim(self.root,dict(context['gmail_claim']),'business')
            return runner or {'status':'failed','code':'SYNTHETIC','receipt':{}}
        with patch.object(service,'adapter_module',return_value=module), \
             patch.object(service,'adapter_generation',return_value=self.generation), \
             patch.object(service,'service_generation',return_value=self.service_generation), \
             patch.object(service,'run_business',side_effect=run):
            result=service.dispatcher(self.config,self.root)(self.job,self.context)
        return result,seen

    def test_gmail_business_profile_cannot_launch_without_claim(self):
        self.config['model_profiles']['b']['apps']=[service.GMAIL]
        module=types.SimpleNamespace(RUNTIME_CONTEXT_VERSION=3,prepare=lambda *_:{'public':'value'})
        with patch.object(service,'adapter_module',return_value=module), \
             patch.object(service,'adapter_generation',return_value=self.generation), \
             patch.object(service,'service_generation',return_value=self.service_generation), \
             patch.object(service,'run_business') as runner:
            result=service.dispatcher(self.config,self.root)(self.job,self.context)
        self.assertEqual(result['code'],'RUNTIME_GMAIL_CLAIM_REQUIRED');runner.assert_not_called()

    def test_claim_is_bound_detached_and_stripped_from_prompt(self):
        claim=self.claim();result,seen=self.dispatch(claim)
        self.assertEqual(result['code'],'SYNTHETIC')
        self.assertNotIn('gmail_claim',seen['prompt']);self.assertNotIn(claim['payload_sha256'],seen['prompt'])
        self.assertEqual(dict(seen['context']['gmail_claim']),claim)
        self.assertEqual(service._validate_gmail_claim(seen['context']['gmail_claim']),claim)
        claim['body_sha256']='9'*64
        self.assertEqual(seen['context']['gmail_claim']['body_sha256'],'2'*64)

    def test_forged_scheduler_and_attestation_identity_fail_before_runner(self):
        for changes,code in (({'job_id':'other.job'},'RUNTIME_GMAIL_CLAIM_INVALID'),
                             ({'slot_id':'other.slot'},'RUNTIME_GMAIL_CLAIM_INVALID'),
                             ({'attempt_id':'other.attempt'},'RUNTIME_GMAIL_CLAIM_INVALID'),
                             ({'host':'b'*64},'RUNTIME_GMAIL_CLAIM_ATTESTATION_MISMATCH'),
                             ({'candidate':'b'*64},'RUNTIME_GMAIL_CLAIM_ATTESTATION_MISMATCH')):
            service._GMAIL_CLAIMS.clear();result,seen=self.dispatch(self.claim(**changes))
            self.assertEqual(result['code'],code);self.assertEqual(seen,{})

    def test_exact_replay_and_payload_conflict_fail_closed(self):
        claim=self.claim();self.dispatch(claim)
        service._GMAIL_CLAIMS.clear()  # Restarting process memory cannot reopen the durable fence.
        result,seen=self.dispatch(claim)
        self.assertEqual(result['code'],'RUNTIME_GMAIL_CLAIM_REPLAY');self.assertEqual(seen,{})
        self.assertEqual(result['status'],'unknown')
        changed=self.claim(body_sha256='3'*64)
        result,seen=self.dispatch(changed)
        self.assertEqual(result['code'],'RUNTIME_GMAIL_CLAIM_CONFLICT');self.assertEqual(seen,{})

    def test_unknown_is_not_downgraded_by_untrusted_claim(self):
        value,_=self.dispatch(self.claim(),{'status':'unknown','code':'BUSINESS_DEADLINE_EXCEEDED',
                            'receipt':{'gmail_claim':self.claim()}})
        self.assertEqual(value['status'],'unknown')
        self.assertEqual(value['code'],'BUSINESS_DEADLINE_EXCEEDED')

    def test_business_and_delivery_source_drift_fail_before_runner(self):
        for key in ('business','delivery'):
            source=self.root/(key+'.py');source.write_text('changed synthetic bytes')
            with patch.dict(service._IMPLEMENTATION_PATHS,{key:source}):
                result,seen=self.dispatch(self.claim())
            self.assertEqual(result['code'],'RUNTIME_GMAIL_IMPLEMENTATION_DRIFT')
            self.assertEqual(seen,{})

    def test_ordinary_generation_does_not_invent_business_source_identity(self):
        with patch.object(service,'_SERVICE_SOURCE_DIGEST',None), \
             patch.dict(service._IMPLEMENTATION_HASHES,{'business':None}):
            generation=service.service_generation()
        self.assertEqual(set(generation['implementations']),{'business','delivery'})
        self.assertIsNone(generation['service']['source_sha256'])
        self.assertIsNone(generation['implementations']['business'])
        delivery=service._IMPLEMENTATION_PATHS['delivery']
        self.assertEqual(generation['implementations']['delivery'],hashlib.sha256(delivery.read_bytes()).hexdigest())

    def test_scheduler_unknown_survives_restart_until_explicit_reconciliation(self):
        from shared.job_runtime.tests.test_engine import EngineTests,job
        from datetime import timedelta
        fixture=EngineTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        allocated={**job(),**self.job}
        unknown={'status':'unknown','code':'BUSINESS_DEADLINE_EXCEEDED','receipt':{'gmail_claim':self.claim()}}
        module=types.SimpleNamespace(RUNTIME_CONTEXT_VERSION=3,prepare=lambda *_:{'gmail_claim':self.claim()})
        # Use the real service result handling with scheduler-generated identities.
        def dispatch(j,c):
            claim=self.claim(slot_id=c['slot_id'],attempt_id=c['attempt_id'])
            module.prepare=lambda *_:{'gmail_claim':claim}
            with patch.object(service,'adapter_module',return_value=module),patch.object(service,'adapter_generation',return_value=self.generation),patch.object(service,'service_generation',return_value=self.service_generation),patch.object(service,'run_business',return_value=unknown):
                return service.dispatcher(self.config,self.root)(j,c)
        engine=fixture.engine(jobs=[allocated],dispatch=dispatch)
        self.assertEqual(engine.tick(fixture.now)['unknown'],1)
        restarted=fixture.engine(jobs=[allocated],dispatch=dispatch)
        later=fixture.now+timedelta(minutes=1)
        self.assertEqual(restarted.tick(later)['dispatched'],0)
        slot=fixture.slots(restarted)[0]['slot_id']
        restarted.resolve_unknown(slot,'failed',{'independent_readback':'synthetic no effect'},later)
        self.assertEqual(restarted.tick(later)['unknown'],1)


if __name__=='__main__':unittest.main()
