import copy
import struct, unittest
from ._support import CAP,REG,fixture,load_package,make_authority,observe,session,setup,state
P=load_package()
from shared.job_runtime.candidates.claude_502_authority_process_v1.canonical import loads_exact
class ProtocolTests(unittest.TestCase):
 def test_error_is_canonical_safe_signed_and_syncs(self):
    a=make_authority(); c=session(a,'runtime','errors')
    with self.assertRaisesRegex(P.AuthorityError,'BINDING_UNKNOWN'): c.call('observe_pre_forward_502',{'binding_handle':'binding:'+'0'*64,'request_ordinal':1,'status':502,'upstream_attempts':0,'upstream_count_delta':0,'submission':'not_submitted','retry_after_seconds':1})
    entry=a.journal_snapshot()[-1]; self.assertEqual(entry['request_sequence'],1); self.assertNotIn('exception',str(entry).lower())
 def test_cleanup_claim_truth_and_best_effort_limits(self):
    a=make_authority(); result=a.revoke_and_cleanup(); self.assertEqual(result.socket_cleanup,'UNOBSERVED_MODEL_ONLY'); self.assertEqual(result.journal_fsync,'UNOBSERVED_MODEL_ONLY'); self.assertEqual(result.process_termination,'UNOBSERVED_MODEL_ONLY'); self.assertEqual(result.key_zeroization,'BEST_EFFORT_ZEROED'); self.assertEqual(bytes(a._key),b'\0'*32)
 def test_memory_transport_only(self):
    left,right=P.MemoryTransport.pair(501); left.send(b'abc',1); self.assertEqual(right.receive(),b'abc'); left.close()

class TransportBoundTests(unittest.TestCase):
 def test_fake_transport_bounds_receive_buffer(self):
    left,right=P.MemoryTransport.pair(501)
    with self.assertRaisesRegex(P.ProtocolError,'TRANSPORT_READ_BOUND_EXCEEDED'): left.send(b'x'*65541,65541)
    self.assertEqual(right.receive(),b'')

class TerminalAndResponseTests(unittest.TestCase):
 def test_preauth_error_terminalizes_client(self):
    a=make_authority(); c=session(a,'runtime','terminal-auth',REG)
    with self.assertRaisesRegex(P.AuthorityError,'CAPABILITY_MISMATCH'): c.call('observe_pre_forward_502',{})
    self.assertTrue(c._closed)
    with self.assertRaisesRegex(P.AuthorityError,'CLIENT_SESSION_CLOSED'): c.call('observe_pre_forward_502',{})
 def response(self,client,**changes):
    value={'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':True,'op':'verify_state','sequence':1,'session_id':'response-test','session_terminal':False,'result':{'valid':True},'signed_error':None}; value.update(changes); return value
 def test_wrong_outer_generation_and_unknown_key(self):
    holder={}; c=P.AuthorityClient(lambda *_:self.response(c,generation=2),CAP,'response-test')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('verify_state',{})
    c=P.AuthorityClient(lambda *_:dict(self.response(c),unknown=True),CAP,'response-test')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('verify_state',{})
 def test_wrong_result_generation(self):
    c=P.AuthorityClient(lambda *_:{'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':True,'op':'register_expected_binding','sequence':1,'session_id':'response-test','session_terminal':False,'result':{'authority_id':'a','binding_handle':'b','binding_digest':'0'*64,'generation':2},'signed_error':None},REG,'response-test','registrar')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('register_expected_binding',{})
 def test_error_binding_mismatch(self):
    payload={'code':'SAFE','design_sha256':'0'*64,'generation':1,'op':'verify_state','sequence':1,'session_id':'response-test','session_terminal':True}; signed={'envelope':{'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'kind':'protocol_error','payload':payload},'signature':'0'*64}
    c=P.AuthorityClient(lambda *_:{'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':False,'op':'verify_state','sequence':1,'session_id':'response-test','session_terminal':True,'result':None,'signed_error':signed},CAP,'response-test')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('verify_state',{})

class ExchangeFailureTaxonomyTests(unittest.TestCase):
 def make_real(self):
    a=make_authority(); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); return a,MemoryServerSession(a,ep)
 def test_before_write_presend_can_retry_same_sequence(self):
    a,server=self.make_real(); calls=[0]
    def exchange(frame,cap):
      calls[0]+=1
      if calls[0]==1: raise P.PreSendFailure('BEFORE_WRITE')
      return server.exchange(frame,cap)
    c=P.AuthorityClient(exchange,REG,'presend','registrar')
    with self.assertRaisesRegex(P.PreSendFailure,'BEFORE_WRITE'): c.call('register_expected_binding',fixture('binding.json'))
    self.assertFalse(c._closed); self.assertEqual(c._sequence,0)
    self.assertEqual(c.call('register_expected_binding',fixture('binding.json'))['generation'],1)
 def test_after_write_before_dispatch_is_unknown_terminal(self):
    left,right=P.MemoryTransport.pair(501)
    def exchange(frame,cap): left.send(frame); raise EOFError('after write')
    c=P.AuthorityClient(exchange,CAP,'after-write')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('verify_state',{})
    self.assertTrue(c._closed); self.assertNotEqual(right.receive(),b'')
    with self.assertRaisesRegex(P.AuthorityError,'CLIENT_SESSION_CLOSED'): c.call('verify_state',{})
 def test_after_commit_before_response_is_unknown_no_replay(self):
    a,server=self.make_real()
    def exchange(frame,cap): server.exchange(frame,cap); raise EOFError('response lost')
    c=P.AuthorityClient(exchange,REG,'after-commit','registrar')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('register_expected_binding',fixture('binding.json'))
    self.assertTrue(c._closed); self.assertIn('after-commit',a._state['sessions'])
 def test_partial_response_is_unknown_terminal(self):
    c=P.AuthorityClient(lambda *_:b'{"partial":',CAP,'partial')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('verify_state',{})
    self.assertTrue(c._closed)
 def test_exact_value_types_and_relationships(self):
    # bool is not an accepted integer timestamp/retry value.
    response={'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':True,'op':'verify_and_consume_proof','sequence':1,'session_id':'typed','session_terminal':False,'result':{'retry_after_seconds':True,'verified_observed_at':0},'signed_error':None}
    c=P.AuthorityClient(lambda *_:response,CAP,'typed')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('verify_and_consume_proof',{})

class ExhaustiveResponseRelationMutationTests(unittest.TestCase):
 def wrapped(self,client,server,mutate):
    client._exchange=lambda frame,cap: mutate(copy.deepcopy(server.exchange(frame,cap)))
    return client
 def assert_unknown_closed(self,client,op,body):
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): client.call(op,body)
    self.assertTrue(client._closed)
 def test_register_relation_mutation(self):
    a=make_authority(); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,REG,'mut-register','registrar')
    def mutate(r): r['result']['binding_digest']='0'*64; return r
    self.assert_unknown_closed(self.wrapped(c,server,mutate),'register_expected_binding',fixture('binding.json'))
 def test_observe_relation_mutation(self):
    a=make_authority(); _,reg=setup(a); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,CAP,'mut-observe')
    body={'binding_handle':reg['binding_handle'],'request_ordinal':1,'status':502,'upstream_attempts':0,'upstream_count_delta':0,'submission':'not_submitted','retry_after_seconds':5}
    def mutate(r): r['result']['signed_proof']['envelope']['payload']['request_ordinal']=2; return r
    self.assert_unknown_closed(self.wrapped(c,server,mutate),'observe_pre_forward_502',body)
 def prepared(self):
    a=make_authority(); binding,reg=setup(a); c=session(a,'runtime','prepare'); proof=observe(c,reg); ready=state(reg); sealed=c.call('seal_initial_state',{'state':ready}); return a,binding,reg,proof,ready,sealed
 def test_verify_proof_relation_mutation(self):
    a,binding,reg,proof,ready,sealed=self.prepared(); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,CAP,'mut-consume'); body={'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':binding}
    def mutate(r): r['result']['retry_after_seconds']+=1; return r
    self.assert_unknown_closed(self.wrapped(c,server,mutate),'verify_and_consume_proof',body)
 def test_seal_relation_mutation(self):
    a=make_authority(); _,reg=setup(a); ready=state(reg); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,CAP,'mut-seal')
    def mutate(r): r['result']['signed_state']['envelope']['payload']['body']['retry_count']=1; return r
    self.assert_unknown_closed(self.wrapped(c,server,mutate),'seal_initial_state',{'state':ready})
 def test_verify_state_relation_mutation(self):
    a,binding,reg,proof,ready,sealed=self.prepared(); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,CAP,'mut-verify'); body={'state_handle':sealed['state_handle'],'signed_state':sealed['signed_state'],'exact_state':sealed['signed_state']['envelope']['payload']}
    def mutate(r): r['result']['valid']=False; return r
    self.assert_unknown_closed(self.wrapped(c,server,mutate),'verify_state',body)
 def transition_ready(self):
    a,binding,reg,proof,ready,sealed=self.prepared(); body={'state_handle':sealed['state_handle'],'signed_state':sealed['signed_state'],'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':binding,'next_state_template':state(reg,'RETRY_WAIT',1)}; return a,body
 def test_transition_relation_mutation(self):
    a,body=self.transition_ready(); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,CAP,'mut-transition')
    def mutate(r): r['result']['consumed_proof']='proof:'+'0'*64; return r
    self.assert_unknown_closed(self.wrapped(c,server,mutate),'transition_retry',body)
 def test_authorize_relation_mutation(self):
    a,body=self.transition_ready(); c0=session(a,'runtime','make-transition'); trans=c0.call('transition_retry',body); a._clock.advance(5); auth_body={'state_handle':trans['state_handle'],'signed_state':trans['signed_successor'],'exact_state':trans['signed_successor']['envelope']['payload']}; from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,CAP,'mut-authorize')
    def mutate(r): r['result']['signed_authorization']['envelope']['payload']['state_handle']='state:'+'0'*64; return r
    self.assert_unknown_closed(self.wrapped(c,server,mutate),'authorize_retry',auth_body)
 def test_revoke_relation_mutation(self):
    a=make_authority(); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,REG,'mut-revoke','registrar')
    def mutate(r): r['result']['revoked']=False; return r
    self.assert_unknown_closed(self.wrapped(c,server,mutate),'revoke_generation',{'generation':1})

class ExactNumericAndBindingMutationTests(unittest.TestCase):
 def test_authority_rejects_bool_float_observation_numerics(self):
    fields={'status':502,'upstream_attempts':0,'upstream_count_delta':0,'request_ordinal':1,'retry_after_seconds':1}
    for name in fields:
      for bad in (True, False, float(fields[name])):
        a=make_authority(); _,reg=setup(a); c=session(a,'runtime','numeric-%s-%s'%(name,type(bad).__name__)); body={'binding_handle':reg['binding_handle'],'request_ordinal':1,'status':502,'upstream_attempts':0,'upstream_count_delta':0,'submission':'not_submitted','retry_after_seconds':1}; body[name]=bad
        with self.subTest(name=name,bad=bad),self.assertRaises(P.AuthorityError): c.call('observe_pre_forward_502',body)
 def test_outer_generation_sequence_bool_float_terminal_unknown(self):
    base={'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':True,'op':'verify_state','sequence':1,'session_id':'numeric-outer','session_terminal':False,'result':{'valid':True},'signed_error':None}
    for field,bad in (('generation',True),('generation',False),('generation',1.0),('sequence',True),('sequence',False),('sequence',1.0)):
      response=dict(base); response[field]=bad; c=P.AuthorityClient(lambda *_:response,CAP,'numeric-outer')
      with self.subTest(field=field,bad=bad),self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('verify_state',{})
 def test_result_timestamp_retry_bool_float_terminal_unknown(self):
    for field in ('retry_after_seconds','verified_observed_at'):
      for bad in (True,False,1.0):
        response={'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':True,'op':'verify_and_consume_proof','sequence':1,'session_id':'numeric-result','session_terminal':False,'result':{'retry_after_seconds':1,'verified_observed_at':1},'signed_error':None}; response['result'][field]=bad
        c=P.AuthorityClient(lambda *_:response,CAP,'numeric-result')
        with self.subTest(field=field,bad=bad),self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('verify_and_consume_proof',{})
 def test_revoked_one_and_revoke_request_bool_float(self):
    for bad in (True,False,1.0):
      a=make_authority(); c=session(a,'registrar','bad-revoke-%s'%type(bad).__name__)
      with self.subTest(bad=bad),self.assertRaises(P.AuthorityError): c.call('revoke_generation',{'generation':bad})
    response={'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':True,'op':'revoke_generation','sequence':1,'session_id':'revoked-one','session_terminal':False,'result':{'generation':1,'revoked':1},'signed_error':None}; c=P.AuthorityClient(lambda *_:response,REG,'revoked-one','registrar')
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('revoke_generation',{'generation':1})
 def test_verify_proof_wrong_expected_binding_relation(self):
    a=make_authority(); b1,r1=setup(a); c=session(a,'runtime','proof-source'); proof=observe(c,r1); b2=dict(b1); b2['request']='other-request'; r2=session(a,'registrar','reg-other').call('register_expected_binding',b2)
    response={'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':True,'op':'verify_and_consume_proof','sequence':1,'session_id':'proof-wrong','session_terminal':False,'result':{'retry_after_seconds':proof['signed_proof']['envelope']['payload']['retry_after_seconds'],'verified_observed_at':proof['signed_proof']['envelope']['payload']['observed_at']},'signed_error':None}
    client=P.AuthorityClient(lambda *_:response,CAP,'proof-wrong'); body={'proof_handle':proof['proof_handle'],'signed_proof':proof['signed_proof'],'exact_expected_bindings':b2}
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): client.call('verify_and_consume_proof',body)
 def test_authorization_before_cooldown_response(self):
    helper=ExhaustiveResponseRelationMutationTests(); a,body=helper.transition_ready(); c0=session(a,'runtime','auth-build'); trans=c0.call('transition_retry',body); a._clock.advance(5); auth_body={'state_handle':trans['state_handle'],'signed_state':trans['signed_successor'],'exact_state':trans['signed_successor']['envelope']['payload']}; from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,ep=P.MemoryTransport.pair(501); server=MemoryServerSession(a,ep); c=P.AuthorityClient(server.exchange,CAP,'auth-early')
    def exchange(frame,cap):
      r=server.exchange(frame,cap); payload=r['result']['signed_authorization']['envelope']['payload']; payload['authorized_at']=auth_body['exact_state']['next_retry_at']-1; return r
    c._exchange=exchange
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): c.call('authorize_retry',auth_body)

class TransitionCrossProofRelationTests(unittest.TestCase):
 def test_cross_binding_proof_handle_and_digest_terminal_unknown(self):
    helper=ExhaustiveResponseRelationMutationTests(); a,body=helper.transition_ready(); valid=session(a,'runtime','transition-valid').call('transition_retry',copy.deepcopy(body))
    forged=copy.deepcopy(body); payload=forged['signed_proof']['envelope']['payload']; payload['binding_digest']='0'*64; payload['binding_handle']='binding:'+'0'*64
    forged_client=P.AuthorityClient(lambda *_:{'design_sha256':'74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3','generation':1,'ok':True,'op':'transition_retry','sequence':1,'session_id':'transition-forged','session_terminal':False,'result':valid,'signed_error':None},CAP,'transition-forged')
    forged['proof_handle']=forged_client._expected_handle('proof',payload)
    with self.assertRaisesRegex(P.UnknownOutcome,'AUTHORITY_DISCONNECT_UNKNOWN'): forged_client.call('transition_retry',forged)
