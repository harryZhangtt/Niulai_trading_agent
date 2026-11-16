import copy, threading, unittest
from ._support import CAP,REG,KEY,fixture,load_package,make_authority,observe,session,setup,state
P=load_package()
from shared.job_runtime.candidates.claude_502_authority_process_v1.contracts import DESIGN_SHA256

class AuthorityTests(unittest.TestCase):
 def flow(self):
    a=make_authority(); binding,reg=setup(a); c=session(a,'runtime','runtime-1'); proof=observe(c,reg,7)
    ready=state(reg); sealed=c.call('seal_initial_state',{'state':ready})
    retry=state(reg,'RETRY_WAIT',1,'attempt-1')
    trans=c.call('transition_retry',{'state_handle':sealed['state_handle'],'signed_state':sealed['signed_state'],'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':binding,'next_state_template':retry})
    return a,binding,reg,c,proof,sealed,retry,trans
 def test_nominal_transition_successor_verify_and_authorize(self):
    a,binding,reg,c,proof,sealed,retry,trans=self.flow(); exact=trans['signed_successor']['envelope']['payload']
    self.assertTrue(c.call('verify_state',{'state_handle':trans['state_handle'],'signed_state':trans['signed_successor'],'exact_state':exact})['valid'])
    with self.assertRaisesRegex(P.AuthorityError,'RETRY_COOLDOWN_ACTIVE'): c.call('authorize_retry',{'state_handle':trans['state_handle'],'signed_state':trans['signed_successor'],'exact_state':exact})
    a._clock.advance(7)
    auth=c.call('authorize_retry',{'state_handle':trans['state_handle'],'signed_state':trans['signed_successor'],'exact_state':exact})
    self.assertTrue(auth['authorization_handle'].startswith('authorization:'))
    with self.assertRaisesRegex(P.AuthorityError,'RETRY_ALREADY_AUTHORIZED'): c.call('authorize_retry',{'state_handle':trans['state_handle'],'signed_state':trans['signed_successor'],'exact_state':exact})
 def test_error_frame_keeps_sequence_synchronized(self):
    a=make_authority(); _,reg=setup(a); c=session(a,'runtime','sync-session')
    with self.assertRaisesRegex(P.AuthorityError,'BINDING_UNKNOWN'): observe(c,{'binding_handle':'binding:'+'0'*64})
    good=observe(c,reg); self.assertTrue(good['proof_handle'].startswith('proof:'))
    self.assertEqual(a._state['sessions']['sync-session']['next_sequence'],3)
 def test_cross_binding_state_proof_transition_rejected(self):
    a=make_authority(); b1,r1=setup(a); b2=dict(b1); b2['attempt']='attempt-2'
    r2=session(a,'registrar','registrar-2').call('register_expected_binding',b2)
    c=session(a,'runtime','cross-session'); proof=observe(c,r2); ready=state(r1); sealed=c.call('seal_initial_state',{'state':ready})
    with self.assertRaisesRegex(P.AuthorityError,'TRANSITION_BINDING_MISMATCH'):
      c.call('transition_retry',{'state_handle':sealed['state_handle'],'signed_state':sealed['signed_state'],'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':b2,'next_state_template':state(r1,'RETRY_WAIT',1,'attempt-1')})
 def test_parallel_sessions_and_replay(self):
    a=make_authority(); _,reg=setup(a); wins=[]; barrier=threading.Barrier(3)
    def worker(i):
      c=session(a,'runtime','parallel-%d'%i); barrier.wait(); wins.append(observe(c,reg)['proof_handle'])
    ts=[threading.Thread(target=worker,args=(i,)) for i in range(2)]
    [t.start() for t in ts]; barrier.wait(); [t.join() for t in ts]
    self.assertEqual(len(wins),2); self.assertNotEqual(wins[0],wins[1])
    # Global session identity cannot be reused under another role.
    bad=session(a,'registrar','parallel-0')
    with self.assertRaisesRegex(P.AuthorityError,'SESSION_IDENTITY_MISMATCH'): bad.call('register_expected_binding',fixture('binding.json'))
 def test_role_capability_escalation_rejected(self):
    a=make_authority()
    with self.assertRaisesRegex(P.AuthorityError,'CAPABILITY_MISMATCH'): session(a,'registrar','escalate-1',CAP).call('register_expected_binding',fixture('binding.json'))
    with self.assertRaisesRegex(P.AuthorityError,'CAPABILITY_MISMATCH'): session(a,'runtime','escalate-2',REG).call('observe_pre_forward_502',{})
 def test_design_bound_in_request_proof_state_journal(self):
    a,binding,reg,c,proof,sealed,retry,trans=self.flow()
    self.assertEqual(proof['signed_proof']['envelope']['design_sha256'],DESIGN_SHA256)
    self.assertEqual(proof['signed_proof']['envelope']['payload']['design_sha256'],DESIGN_SHA256)
    self.assertEqual(sealed['signed_state']['envelope']['design_sha256'],DESIGN_SHA256)
    self.assertTrue(all(e['design_sha256']==DESIGN_SHA256 for e in a.journal_snapshot()))
    request={'body':{},'design_sha256':'0'*64,'generation':1,'op':'verify_state','role':'runtime','sequence':1,'session_id':'bad-design'}
    with self.assertRaisesRegex(P.ProtocolError,'DESIGN_MISMATCH'): a.dispatch(request,501,CAP)
 def test_proof_consume_one_shot(self):
    a=make_authority(); binding,reg=setup(a); c=session(a,'runtime','consume'); proof=observe(c,reg)
    body={'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':binding}
    self.assertEqual(c.call('verify_and_consume_proof',body)['retry_after_seconds'],5)
    with self.assertRaisesRegex(P.AuthorityError,'PROOF_ALREADY_CONSUMED'): c.call('verify_and_consume_proof',body)
 def test_forwarded_502_and_nonpositive_retry_rejected(self):
    for field,value,code in [('upstream_attempts',1,'NOT_PREFORWARD_502'),('upstream_count_delta',1,'NOT_PREFORWARD_502'),('submission','submitted','NOT_PREFORWARD_502'),('retry_after_seconds',0,'RETRY_AFTER_INVALID')]:
      a=make_authority(); _,reg=setup(a); c=session(a,'runtime','reject-'+field)
      body={'binding_handle':reg['binding_handle'],'request_ordinal':1,'status':502,'upstream_attempts':0,'upstream_count_delta':0,'submission':'not_submitted','retry_after_seconds':1}; body[field]=value
      with self.subTest(field=field),self.assertRaisesRegex(P.AuthorityError,code): c.call('observe_pre_forward_502',body)

class ReplayTamperTests(unittest.TestCase):
 def test_same_session_exact_replay_rejected(self):
    a=make_authority(); request={'body':fixture('binding.json'),'design_sha256':DESIGN_SHA256,'generation':1,'op':'register_expected_binding','role':'registrar','sequence':1,'session_id':'replay-session'}
    a.dispatch(request,501,REG)
    with self.assertRaisesRegex(P.AuthorityError,'SESSION_SEQUENCE_MISMATCH'): a.dispatch(request,501,REG)
 def test_signed_successor_tamper_rejected_and_sequence_recovers(self):
    owner=AuthorityTests(); a,binding,reg,c,proof,sealed,retry,trans=owner.flow(); exact=trans['signed_successor']['envelope']['payload']; bad=copy.deepcopy(trans['signed_successor']); bad['signature']='0'*64
    with self.assertRaisesRegex(P.AuthorityError,'SIGNATURE_INVALID'): c.call('verify_state',{'state_handle':trans['state_handle'],'signed_state':bad,'exact_state':exact})
    self.assertTrue(c.call('verify_state',{'state_handle':trans['state_handle'],'signed_state':trans['signed_successor'],'exact_state':exact})['valid'])

class ReviewTwoStateTests(unittest.TestCase):
 def test_seal_rejects_binding_identity_mismatch_and_retry_phase(self):
    a=make_authority(); _,reg=setup(a); c=session(a,'runtime','seal-negative')
    bad=state(reg); bad['slot']='other-slot'
    with self.assertRaisesRegex(P.AuthorityError,'STATE_BINDING_IDENTITY_MISMATCH'): c.call('seal_initial_state',{'state':bad})
    retry=state(reg,'RETRY_WAIT',1)
    with self.assertRaisesRegex(P.AuthorityError,'INITIAL_STATE_PHASE_INVALID'): c.call('seal_initial_state',{'state':retry})
 def test_transition_rejects_template_identity_mismatch(self):
    a=make_authority(); binding,reg=setup(a); c=session(a,'runtime','transition-id'); proof=observe(c,reg); ready=state(reg); sealed=c.call('seal_initial_state',{'state':ready}); retry=state(reg,'RETRY_WAIT',1); retry['attempt']='forged-attempt'
    with self.assertRaisesRegex(P.AuthorityError,'STATE_BINDING_IDENTITY_MISMATCH'):
      c.call('transition_retry',{'state_handle':sealed['state_handle'],'signed_state':sealed['signed_state'],'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':binding,'next_state_template':retry})
 def test_forged_retry_provenance_rejected(self):
    owner=AuthorityTests(); a,binding,reg,c,proof,sealed,retry,trans=owner.flow(); exact=copy.deepcopy(trans['signed_successor']['envelope']['payload']); exact['consumed_proof_handle']='proof:'+'0'*64
    forged=a._artifact('campaign_state',exact); handle=a._handle('state',exact); a._state['states'][handle]=forged; a._clock.advance(7)
    with self.assertRaisesRegex(P.AuthorityError,'RETRY_PROVENANCE_INVALID'): c.call('authorize_retry',{'state_handle':handle,'signed_state':forged,'exact_state':exact})
