import hashlib,http.client,unittest
from ._support import Clock,raw
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import EffectGuard,ExecutionBinding
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.gateway import GatewayObserver
class GatewayTests(unittest.TestCase):
 def make(self):
  b=ExecutionBinding('j1234567','s1234567','a1234567','o1234567','p1234567','a'*64,'gpt-6.1-sol','b'*64,'c'*64);c=Clock();return GatewayObserver('a'*64,hashlib.sha256(('o1234567'+'a'*64).encode()).hexdigest(),lambda _:raw('fake_terminal_exact.jsonl'),b,EffectGuard('0.01','0.02',1000,c))
 def test_actual_loopback_second_rejected_closed(self):
  g=self.make();port=g.start();h={'X-R6-Fingerprint':g.expected_fingerprint,'X-R6-Admission':g.expected_admission_key};statuses=[]
  for _ in range(2):
   c=http.client.HTTPConnection('127.0.0.1',port);c.request('POST','/backend-api/codex/responses',b'{}',h);r=c.getresponse();statuses.append(r.status);r.read();c.close()
  x=g.close();self.assertEqual(statuses,[200,409]);self.assertTrue(x['listener_closed'] and x['server_fd_closed'] and x['thread_stopped']);self.assertEqual(x['upstream_attempts'],1)
 def test_no_status_or_reconciliation(self):g=self.make();self.assertFalse(hasattr(g,'status'));self.assertFalse(hasattr(g,'reconcile'));g.start();g.close()
if __name__=='__main__':unittest.main()
