import copy, unittest
from ._support import CAP,REG,KEY,fixture,load_package,make_authority,observe,session,setup,state
P=load_package()
from shared.job_runtime.candidates.claude_502_authority_process_v1.contracts import DESIGN_SHA256

def req(op,body,sid,role='runtime'):
 return {'body':body,'design_sha256':DESIGN_SHA256,'generation':1,'op':op,'role':role,'sequence':1,'session_id':sid}
class RecoveryTests(unittest.TestCase):
 def case(self,op):
    a=make_authority(); binding,reg=setup(a); c=session(a,'runtime','setup-runtime'); proof=observe(c,reg); ready=state(reg)
    sealed=c.call('seal_initial_state',{'state':ready})
    if op=='register_expected_binding': return a,req(op,dict(binding,attempt='attempt-new'),'crash-reg','registrar'),REG
    if op=='observe_pre_forward_502': return a,req(op,{'binding_handle':reg['binding_handle'],'request_ordinal':2,'status':502,'upstream_attempts':0,'upstream_count_delta':0,'submission':'not_submitted','retry_after_seconds':2},'crash-obs'),CAP
    if op=='seal_initial_state': return a,req(op,{'state':dict(ready,attempt='attempt-new')},'crash-seal'),CAP
    if op=='verify_state': return a,req(op,{'state_handle':sealed['state_handle'],'signed_state':sealed['signed_state'],'exact_state':sealed['signed_state']['envelope']['payload']},'crash-verify'),CAP
    if op=='verify_and_consume_proof': return a,req(op,{'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':binding},'crash-consume'),CAP
    retry=state(reg,'RETRY_WAIT',1,'attempt-1'); trans_body={'state_handle':sealed['state_handle'],'signed_state':sealed['signed_state'],'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':binding,'next_state_template':retry}
    if op=='transition_retry': return a,req(op,trans_body,'crash-transition'),CAP
    trans=c.call('transition_retry',trans_body); a._clock.advance(5)
    return a,req('authorize_retry',{'state_handle':trans['state_handle'],'signed_state':trans['signed_successor'],'exact_state':trans['signed_successor']['envelope']['payload']},'crash-authorize'),CAP
 def recover(self,entries): return P.Authority.from_journal(entries,501,CAP,REG,1,KEY,P.ManualClock(1000))
 def test_before_after_commit_recovery_every_operation(self):
    operations=('register_expected_binding','observe_pre_forward_502','seal_initial_state','verify_state','verify_and_consume_proof','transition_retry','authorize_retry')
    for op in operations:
      for point in (P.CrashPoint.BEFORE_COMMIT,P.CrashPoint.AFTER_COMMIT):
        a,request,cap=self.case(op); before=copy.deepcopy(a._state); before_journal=a.journal_snapshot()
        with self.subTest(op=op,point=point),self.assertRaises(P.CrashSimulated): a.dispatch(request,501,cap,point)
        entries=a.journal_snapshot(); recovered=self.recover(entries)
        if point is P.CrashPoint.BEFORE_COMMIT:
          self.assertEqual(entries,before_journal); self.assertEqual(recovered._state,before)
        else:
          self.assertEqual(recovered._state,a._state); self.assertNotEqual(a._state,before)
 def test_append_failure_rolls_back(self):
    a,request,cap=self.case('observe_pre_forward_502'); before=copy.deepcopy(a._state); entries=a.journal_snapshot(); a._journal.fail_next_append=True
    with self.assertRaisesRegex(P.UnknownOutcome,'JOURNAL_APPEND_UNKNOWN'): a.dispatch(request,501,cap)
    self.assertEqual(a._state,before); self.assertEqual(a.journal_snapshot(),entries)
 def test_tampered_journal_and_wrong_key_rejected(self):
    a,_,_=self.case('observe_pre_forward_502'); entries=list(a.journal_snapshot()); entries[-1]['state_snapshot']['revoked']=True
    with self.assertRaisesRegex(P.UnknownOutcome,'JOURNAL_RECOVERY_INVALID'): self.recover(entries)
    with self.assertRaisesRegex(P.UnknownOutcome,'JOURNAL_RECOVERY_INVALID'): P.Authority.from_journal(a.journal_snapshot(),501,CAP,REG,1,b'x'*32)

class RecoveryClockTests(unittest.TestCase):
 def test_recovery_restores_wall_clock_floor(self):
    a=make_authority(); binding,reg=setup(a); a._clock.advance(20); observe(session(a,'runtime','clock-before'),reg)
    recovered=P.Authority.from_journal(a.journal_snapshot(),501,CAP,REG,1,KEY,P.ManualClock(1))
    session(recovered,'runtime','clock-after').call('observe_pre_forward_502',{'binding_handle':reg['binding_handle'],'request_ordinal':2,'status':502,'upstream_attempts':0,'upstream_count_delta':0,'submission':'not_submitted','retry_after_seconds':1})
    self.assertGreaterEqual(recovered.journal_snapshot()[-1]['timestamp'],a.journal_snapshot()[-1]['timestamp'])

class RevocationRecoveryTests(unittest.TestCase):
 def test_revocation_committed_before_zeroization_and_recovered(self):
    a=make_authority(); setup(a); a.revoke_and_cleanup(); entries=a.journal_snapshot(); self.assertEqual(entries[-1]['event'],'generation_revoked'); self.assertTrue(entries[-1]['state_snapshot']['revoked'])
    recovered=P.Authority.from_journal(entries,501,CAP,REG,1,KEY,P.ManualClock(1000)); self.assertTrue(recovered._state['revoked'])
    with self.assertRaisesRegex(P.AuthorityError,'GENERATION_REVOKED'): recovered.dispatch(req('verify_state',{},'revoked-session'),501,CAP)
