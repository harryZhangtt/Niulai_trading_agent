import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from shared.research_sources.artifacts import ROOT,save,read,digest,SourceError
from shared.web_access import skill_bridge as b
from shared.web_access.policy import load_config


class SkillBridgeTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.research-sources/web-access-test-tmp';base.mkdir(exist_ok=True,parents=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name);self.config=load_config();self.calls=0
        for target,value in [('CLIENT',self.path/'client'),('HOST',self.path/'host')]:
            p=patch.object(b,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(b,'load_config',return_value=self.config);p.start();self.addCleanup(p.stop)
        self.guide=patch.object(b,'_execute',return_value=b'[ego-browser:skill] end of guide v2.2.0');self.guide.start();self.addCleanup(self.guide.stop)

    def reader(self,config,decision,*,output_directory):
        self.calls+=1
        text=save(output_directory,b'Step 5: complete the task. Troubleshooting.',suffix='txt')
        obs=save(output_directory,{'status':'observed','observed_url':b.URL,'requested_url':b.URL,
            'cleanup_verified':True,'truncated':False,'config_sha256':digest(config),'snapshot_ref':text,'task_space':'fixture'})
        return {'status':'observed','receipt_ref':obs}

    def host(self,reader=None):
        return b.Host(str(uuid.uuid4()),reader=reader or self.reader)

    def request(self,host,value=None):
        (host.client/'request.json').write_text(json.dumps(value or host.request))

    def test_duplicate_requests_have_one_host_execution_and_private_verification(self):
        h=self.host();self.request(h);h.tick();h.tick();h.tick()
        self.assertEqual(self.calls,1)
        self.assertTrue(h.verify()['verified'])
        self.assertEqual(b.client(h.operation)['status'],'observed')

    def test_model_cannot_supply_url_or_config(self):
        h=self.host();self.request(h,{**h.request,'url':'https://evil.example/'})
        with self.assertRaisesRegex(SourceError,'SKILL_BRIDGE_REQUEST_REJECTED'):h.tick()
        self.assertEqual(self.calls,0)
        self.assertFalse((h.out/'claim.json').exists())

    def test_forged_client_response_cannot_satisfy_host_postcondition(self):
        h=self.host();(h.client/'response.json').write_text(json.dumps({'operation_id':h.operation,'status':'observed'}))
        self.assertFalse(h.verify()['verified'])

    def test_unknown_or_failed_host_effect_is_fenced_and_sanitized(self):
        def fail(*args,**kwargs):self.calls+=1;raise RuntimeError('SYNTHETIC_PRIVATE_CANARY')
        h=self.host(fail);self.request(h);h.tick();h.tick()
        self.assertEqual(self.calls,1)
        r=read(json.loads((h.out/'result.json').read_text()))
        self.assertEqual(r['effect_state'],'unknown')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY',json.dumps(r))
        self.assertFalse(h.verify()['verified'])
        with self.assertRaisesRegex(SourceError,'SKILL_BRIDGE_RESUME_UNSAFE'):
            b.Host(h.operation,reader=fail,resume=True)

    def test_auth_contention_resume_requires_no_client_request_or_host_claim(self):
        h=self.host();again=b.Host(h.operation,reader=self.reader,resume=True)
        self.request(again);again.tick();self.assertEqual(self.calls,1)
        with self.assertRaisesRegex(SourceError,'SKILL_BRIDGE_RESUME_UNSAFE'):
            b.Host(h.operation,reader=self.reader,resume=True)


if __name__=='__main__':unittest.main()
