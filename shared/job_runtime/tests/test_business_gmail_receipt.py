"""Frozen sanitized Gmail receipt handoff; all values are synthetic."""
from pathlib import Path
import json
import unittest

from shared.job_runtime.business import SummaryError, _final, _gmail_receipt, _gmail_host_evidence, _digest, _metadata, _ObservedOutput


ROOT=Path(__file__).resolve().parents[3]
DIGEST='a'*64


def complete(**changes):
    value={
        'status':'sent',
        'message_id':'abcdef1234567890',
        'email_message_id':'ABCDEF1234567890',
        'email_thread_id':'1234567890abcdef',
        'send_event_id':'send-event-0001',
        'read_event_id':'read-event-0001',
        'recipient_sha256':DIGEST,
        'subject_sha256':'b'*64,
        'body_sha256':'c'*64,
        'raw_readback_sha256':'d'*64,
        'readback_verified_at':'2026-11-05T08:09:10+00:00',
        'gmail_verified':True,
        'delivery_verified':True,
    }
    value.update(changes)
    return value


class GmailReceiptContractTests(unittest.TestCase):
    def parse(self,value):
        return _final(json.dumps(value),'business',ROOT)

    def rejected(self,value,field=None):
        with self.assertRaises(SummaryError) as raised:self.parse(value)
        if field is not None:self.assertEqual(raised.exception.field,field)

    def test_complete_sanitized_host_handoff_is_bounded(self):
        expected=complete();expected['email_message_id']=expected['email_message_id'].lower()
        self.assertEqual(self.parse(complete()),expected)

    def test_model_verified_flags_do_not_require_host_fields(self):
        value={'status':'sent','gmail_verified':True,'delivery_verified':True}
        self.assertEqual(self.parse(value),value)

    def test_send_and_read_event_ids_are_atomic_and_aliases_must_match(self):
        value=complete();value.pop('read_event_id')
        self.rejected(value,'send_read_event_ids')
        self.rejected(complete(email_message_id='1111111111111111'),'email_message_id')

    def test_unknown_ambiguous_and_malformed_values_are_rejected(self):
        cases=(('message_id','unknown'),('send_event_id','ambiguous'),
               ('recipient_sha256','A'*64),('readback_verified_at','2026-11-05T08:09:10'))
        for field,bad in cases:
            with self.subTest(field=field):self.rejected(complete(**{field:bad}),field)

    def test_raw_content_and_secret_bearing_output_never_enter_receipt(self):
        for field in ('recipient','subject','body','tool_args','tool_result'):
            self.rejected({**complete(),field:'synthetic raw content'})
        self.rejected({**complete(), 'code':'bearer synthetic-secret-value'})

    def test_partial_unverified_and_legacy_summaries_remain_compatible(self):
        partial={'status':'partial','message_id':'abcdef1234567890','delivery_verified':False}
        self.assertEqual(self.parse(partial),partial)
        legacy={'status':'completed','message_id':None,'email_message_id':None,
                'gmail_verified':False,'delivery_verified':False}
        self.assertEqual(self.parse(legacy),legacy)


class HostEvidenceTests(unittest.TestCase):
    """Synthetic, never live Gmail. Wire envelope: Codex CLI 0.166 contract
    content text / structured_content supplied in review; no live trace claimed.
    Tool/payload provenance: jobs/daily-business-prompt.md, scheduled-e2e-prompt.md,
    niulai_runtime/delivery.py validate_payload and replay.py from_raw.
    """
    def setUp(self):
        from email.message import EmailMessage
        from email import policy
        import base64
        self.encode=lambda b:base64.urlsafe_b64encode(b).decode()
        self.payload={'to':'canary@example.invalid','subject':'[CODEX] synthetic',
            'payload':{'mime_type':'multipart/mixed','parts':[]}}
        msg=EmailMessage(policy=policy.SMTP)
        msg['To']=self.payload['to'];msg['From']=self.payload['to'];msg['Subject']=self.payload['subject']
        msg.set_content('<html>HTML_CANARY</html>',subtype='html')
        # Exact bytes from generated MIME, including its final CRLF.
        html=msg.get_payload(decode=True).replace(b'\n',b'\r\n')
        self.payload['payload']['parts'].append({'mime_type':'text/html','charset':'utf-8','body':{'base64_url_content':self.encode(html)}})
        for n in (1,2):
            pdf=(f'%PDF-1.4 ATTACHMENT_CANARY_{n} %%EOF').encode()+b' %%EOF'
            msg.add_attachment(pdf,maintype='application',subtype='pdf',filename=f'{n}.pdf')
            self.payload['payload']['parts'].append({'mime_type':'application/pdf','filename':f'{n}.pdf','content_disposition':'attachment','body':{'base64_url_content':self.encode(pdf)}})
        self.mime=msg.as_bytes();self.rawmime=self.encode(self.mime)
        self.mid='abcdef1234567890';self.tid='1234567890abcdef';self.dmid='1111111111111111'
        self.events=[{'type':'thread.started','thread_id':'synthetic-thread'},
            self.event('gmail_get_profile','profile-event-001',{},
                {'emailAddress':'Sender <CANARY@EXAMPLE.INVALID>','messagesTotal':3,'threadsTotal':2,'historyId':'123'}),
            self.event('gmail_create_draft','draft-event-001',self.payload,{'id':'draft-001','message':{'id':self.dmid,'threadId':self.tid}}),
            self.read(self.dmid,'draft-read-001'),
            self.event('gmail_send_draft','send-event-001',{'draft_id':'draft-001'},{'id':self.mid,'threadId':self.tid}),
            self.read(self.mid,'sent-read-001')]
        from shared.job_runtime.business import _gmail_host_observation
        evidence=_gmail_host_observation(self.raw())[0]
        self.claim={'schema_version':1,'job_id':'job.synthetic','slot_id':'slot.synthetic',
                    'attempt_id':'attempt.synthetic','host':'host-0001','run':'run-00001',
                    'candidate':'candidate-001','mode':'raw',
                    **{k:evidence[k] for k in ('delivery_payload_sha256','recipient_sha256','subject_sha256',
                                               'sender_identity_sha256','html_sha256','attachments_sha256')}}
        self.claim['profile_identity_sha256']=self.claim['sender_identity_sha256']
        self.bind()
        self.final={'status':'sent','gmail_verified':True,'delivery_verified':True}

    def bind(self):
        self.claim['payload_sha256']=_digest(json.dumps({k:v for k,v in self.claim.items() if k!='payload_sha256'},sort_keys=True,separators=(',',':')))

    def claim_for(self,mode,evidence):
        claim={k:self.claim[k] for k in ('schema_version','job_id','slot_id','attempt_id','host','run','candidate')}
        claim.update(mode=mode,**{k:evidence[k] for k in ('delivery_payload_sha256','recipient_sha256','subject_sha256','sender_identity_sha256')})
        claim['profile_identity_sha256']=claim['sender_identity_sha256']
        for key in (('body_sha256',) if mode=='text' else ('html_sha256','attachments_sha256')):claim[key]=evidence[key]
        self.claim=claim;self.bind()

    def event(self,name,eid,args,data):
        return {'type':'item.completed','item':{'type':'mcp_tool_call','tool':name,'id':eid,
            'status':'completed','arguments':args,'result':{'structured_content':data}}}

    def read(self,mid,eid):
        return self.event('gmail_read_email',eid,{'message_id':mid,'format':'raw'},
            {'id':mid,'threadId':self.tid,'raw':self.rawmime})

    def raw(self):
        lifecycle=self.events+[{'type':'item.completed','item':{'type':'agent_message','text':json.dumps(self.final if hasattr(self,'final') else {'status':'sent'})}},
                               {'type':'turn.completed'}]
        return _ObservedOutput('\n'.join(json.dumps(e) for e in lifecycle).encode(),
            [e.get('timestamp','2026-11-05T08:09:10+00:00') for e in lifecycle])

    def receipt(self,started=None,ended=None,workspace=ROOT):
        meta=_metadata(self.raw(),started,ended)
        return _gmail_receipt(meta['gmail_observation'],self.final,self.claim,workspace)

    def untrusted(self):self.assertEqual(self.receipt()['final_evidence_trust'],'untrusted_model_output')

    def test_raw_draft_and_simple_paths(self):
        import hashlib
        for simple in (False,True):
            if simple:self.events=self.events[:2]+[self.event('gmail_send_email','simple-send-001',self.payload,{'id':self.mid,'threadId':self.tid}),self.read(self.mid,'simple-read-001')]
            receipt=self.receipt()
            self.assertEqual(receipt['final_evidence_trust'],'trusted_operational_host_evidence')
            self.assertEqual(receipt['gmail_operational_evidence']['raw_readback_sha256'],hashlib.sha256(self.mime).hexdigest())
            for secret in ('CANARY','example.invalid','[CODEX] synthetic','rawmime'):
                self.assertNotIn(secret,json.dumps(receipt))

    def test_transport_bytes_are_bound_by_raw_claim(self):
        changed=self.encode(b'X-Synthetic: changed\r\n'+self.mime)
        for event in self.events:
            data=event.get('item',{}).get('result',{}).get('structured_content',{})
            if 'raw' in data:data['raw']=changed
        receipt=self.receipt()
        self.assertEqual(receipt['final_evidence_trust'],'trusted_operational_host_evidence')
        self.assertIn('gmail_operational_evidence',receipt)

    def test_identity_hash_and_strict_variants(self):
        for key in ('host','run','candidate'):
            old=self.claim[key];self.claim[key]=old+'x';self.untrusted()
            self.assertNotIn('gmail_claim',self.receipt())
            self.claim[key]=old
        self.claim['unexpected']='x';self.untrusted()

    def test_text_claim_cannot_attest_draft_or_attachment_send(self):
        evidence=_metadata(self.raw())['gmail_observation'][0]
        # A text claim cannot attest the already-observed draft/raw workflow.
        text={**evidence,'body_sha256':'0'*64}
        self.claim_for('text',text);self.untrusted()
        self.events=self.events[:2]+[self.event('gmail_send_email','direct-send-001',self.payload,
            {'id':self.mid,'threadId':self.tid}),self.read(self.mid,'direct-read-001')]
        self.untrusted()

    def test_lifecycle_boundaries(self):
        import copy
        original=copy.deepcopy(self.events)
        for events in (original[1:]+original[:1],original[:1]+original,
                       original[:1]+[{'type':'turn.completed'}]+original[1:],
                       original+[{'type':'turn.completed'}]):
            self.events=events;self.untrusted()

    def test_display_names_and_uppercase_ids(self):
        self.mime=self.mime.replace(b'To: canary@',b'To: Recipient <canary@').replace(
            b'From: canary@',b'From: Sender <canary@').replace(b'example.invalid\r\n',b'example.invalid>\r\n')
        self.rawmime=self.encode(self.mime)
        for event in self.events[1:]:
            item=event['item'];data=item['result']['structured_content']
            if 'raw' in data:data['raw']=self.rawmime
            for target in (data,data.get('message',{})):
                for key in ('id','threadId'):
                    if key in target and key!='id' or key in target and target[key]!= 'draft-001':target[key]=target[key].upper()
            if 'message_id' in item['arguments']:item['arguments']['message_id']=item['arguments']['message_id'].upper()
        receipt=self.receipt()
        self.assertEqual(receipt['final_evidence_trust'],'trusted_operational_host_evidence')
        self.assertEqual(receipt['gmail_operational_evidence']['message_id'],self.mid)
        self.assertEqual(self.parse_upper_ids()['email_thread_id'],self.tid)

    def parse_upper_ids(self):
        return _final(json.dumps(complete(message_id=self.mid.upper(),email_thread_id=self.tid.upper())), 'business',ROOT)

    def test_bad_final_preserves_host_reconciliation(self):
        observation=_metadata(self.raw())['gmail_observation']
        for final in (None,{'body':'bearer SECRET_CANARY'}, {'status':'invalid'}):
            receipt=_gmail_receipt(observation,final,self.claim,ROOT)
            self.assertEqual(receipt['gmail_claim'],self.claim)
            self.assertEqual(receipt['gmail_operational_evidence'],observation[0])
            self.assertEqual(receipt['final_evidence_trust'],'untrusted_model_output')
            self.assertNotIn('CANARY',json.dumps(receipt))

    def test_aliases_and_content_variants(self):
        for e in self.events[1:]:
            e['item']['tool']='mcp__codex_apps__'+e['item']['tool']
            data=e['item']['result']['structured_content']
            e['item']['arguments']=json.dumps(e['item']['arguments'])
            e['item']['result']={'content':[{'type':'text','text':json.dumps(data)}],'structured_content':json.dumps(data)}
        receipt=self.receipt()
        self.assertEqual(receipt['final_evidence_trust'],'trusted_operational_host_evidence')
        self.assertTrue(all(n.startswith('mcp__codex_apps__') for n in receipt['gmail_tool_names']))

    def test_allowed_other_tools(self):
        for index,name in enumerate(('sites_get_site','metadata_search')):
            self.events.insert(1,self.event(name,f'other-event-00{index}',{},
                {'emailAddress':self.payload['to']} if name=='gmail_get_profile' else {}))
        self.events.insert(1,{'type':'item.completed','item':{'type':'command_execution','command':'synthetic'}})
        self.assertEqual(self.receipt()['final_evidence_trust'],'trusted_operational_host_evidence')

    def test_profile_observation_binds_sender_independently_of_recipient(self):
        self.mime=self.mime.replace(b'From: canary@example.invalid',b'From: Sender <sender@example.invalid>')
        self.rawmime=self.encode(self.mime)
        self.events[1]['item']['result']['structured_content']['emailAddress']='Sender <SENDER@EXAMPLE.INVALID>'
        for event in self.events[2:]:
            data=event['item']['result']['structured_content']
            if 'raw' in data:data['raw']=self.rawmime
        evidence=_metadata(self.raw())['gmail_observation'][0]
        self.claim_for('raw',evidence)
        self.assertNotEqual(evidence['recipient_sha256'],evidence['profile_identity_sha256'])
        self.assertEqual(self.receipt()['final_evidence_trust'],'trusted_operational_host_evidence')
        self.events.pop(1)
        self.final.update(profile_identity_sha256=self.claim['profile_identity_sha256'])
        self.untrusted()

    def test_required_profile_adversarial_matrix(self):
        import copy
        original=copy.deepcopy(self.events)
        profile=original[1]
        variants=[original[:1]+original[2:],
                  original[:2]+[copy.deepcopy(profile)]+original[2:],
                  original[:1]+original[2:]+[profile],
                  [profile]+original[:1]+original[2:]]
        duplicate=copy.deepcopy(profile);duplicate['item']['id']='profile-second-001'
        variants.append(original[:2]+[duplicate]+original[2:])
        for events in variants:
            self.events=copy.deepcopy(events);self.untrusted()
        changes=[{'status':value} for value in ('failed','unknown','in_progress')]
        changes += [{'id':value} for value in ('x','bad id','x'*257)]
        changes += [{'arguments':{'mailbox':'canary@example.invalid'}}, {'error':{}},
                    {'result':{'structuredContent':{}}},
                    {'result':{'structured_content':'{"emailAddress":"a@b.invalid","emailAddress":"canary@example.invalid"}'}}]
        for data in ({}, {'emailAddress':None}, {'emailAddress':['canary@example.invalid']},
                     {'emailAddress':'bad'}, {'emailAddress':'a@example.invalid,b@example.invalid'},
                     {'emailAddress':'other@example.invalid'},
                     {'emailAddress':'canary@example.invalid','email':'other@example.invalid'},
                     {'emailAddress':'x'*1048577},
                     {'emailAddress':'canary@example.invalid','status':'unknown'},
                     {'emailAddress':'canary@example.invalid','isError':True}):
            changes.append({'result':{'structured_content':data}})
        for change in changes:
            self.events=copy.deepcopy(original);self.events[1]['item'].update(change);self.untrusted()
        for stamp in ('naive','2026-11-04T00:00:00+00:00','2026-11-06T00:00:00+00:00'):
            self.events=copy.deepcopy(original);self.events[1]['timestamp']=stamp
            self.assertEqual(self.receipt('2026-11-05T00:00:00+00:00','2026-11-05T23:59:59+00:00')['final_evidence_trust'],'untrusted_model_output')
        self.events=original
        for key in ('sender_identity_sha256','profile_identity_sha256'):
            old=self.claim[key];self.claim[key]='0'*64;self.bind();self.untrusted()
            self.claim[key]=old;self.bind()

    def test_observed_profile_mismatch_cannot_attest_sender(self):
        self.events.insert(1,self.event('gmail_get_profile','profile-event-001',{},
            {'emailAddress':'Different <other@example.invalid>'}))
        self.untrusted()

    def test_tool_after_final_and_failed_turn_invalidate_lifecycle(self):
        import copy
        original=copy.deepcopy(self.events)
        for event in (self.event('metadata_search','late-event-001',{},{}),
                      {'type':'turn.failed','error':{'message':'failure'}}):
            self.events=copy.deepcopy(original)
            raw=self.raw()
            lines=bytes(raw).splitlines()
            lines.insert(-1,json.dumps(event).encode())
            stream=_ObservedOutput(b'\n'.join(lines),list(raw.observations[:-1])+[raw.observations[-1]]*2)
            self.assertIsNone(_metadata(stream)['gmail_observation'])

    def test_unknown_duplicate_conflict_and_order(self):
        import copy
        original=copy.deepcopy(self.events)
        variants=[original+[original[-1]],original+[original[-2]],original[:3],
            original[:1]+[original[-1]]+original[1:],original+[self.event('gmail_delete_email','unknown-event-001',{}, {})]]
        for events in variants:self.events=events;self.untrusted()
        self.events=original
        self.events[-1]['item']['arguments']['message_id']='2222222222222222';self.untrusted()

    def test_envelope_duplicates_and_secret_canaries(self):
        import copy
        original=copy.deepcopy(self.events)
        for result in ({'structuredContent':{}},{'structured_content':'{"id":1,"id":2}'},
                       {'content':[{'type':'text','text':'{"raw":"bearer SECRET_CANARY","raw":"x"}'}]},
                       {'structured_content':{},'content':[{'type':'text','text':'{"conflict":1}'}]}):
            self.events=copy.deepcopy(original);self.events[-1]['item']['result']=result
            self.untrusted();self.assertNotIn('CANARY',json.dumps(self.receipt()))
        self.assertIsNone(_metadata(self.raw()+b'\n{"type":"x","type":"y"}')['gmail_observation'])

    def test_timestamp_bounds_and_order(self):
        for e in self.events[1:]:e['timestamp']='2026-11-05T08:09:10+00:00'
        start='2026-11-05T08:09:09+00:00';end='2026-11-05T08:09:11+00:00'
        self.assertEqual(self.receipt(start,end)['final_evidence_trust'],'trusted_operational_host_evidence')
        for stamp in ('2026-11-04T08:09:10+00:00','2026-11-06T08:09:10+00:00','naive'):
            self.events[-1]['timestamp']=stamp
            self.assertEqual(self.receipt(start,end)['final_evidence_trust'],'untrusted_model_output')
        self.events[-1]['timestamp']='2026-11-05T08:09:09+00:00';self.untrusted()

    def test_raw_attachment_tamper_and_claim_mismatch(self):
        self.events[-1]['item']['result']['structured_content']['raw']=self.encode(self.mime.replace(b'HTML_CANARY',b'HTML_TAMPER'))
        self.untrusted()
        self.events[-1]['item']['result']['structured_content']['raw']=self.rawmime
        for key in self.claim:
            saved=self.claim[key];self.claim[key]='invalid';self.untrusted();self.claim[key]=saved

    def test_both_attachment_canaries_bind_and_malformed_encoding_fails(self):
        import copy
        original=copy.deepcopy(self.events)
        for index in (1,2):
            self.events=copy.deepcopy(original)
            self.events[2]['item']['arguments']['payload']['parts'][index]['body']['base64_url_content']=self.encode(b'%PDF-CHANGED %%EOF')
            self.untrusted()
        self.events=original
        evidence=_metadata(self.raw())['gmail_observation'][0]
        self.claim_for('raw',evidence)
        for raw in ('not base64!',self.rawmime+'==='):
            self.events[-1]['item']['result']['structured_content']['raw']=raw
            self.untrusted()

    def test_run_enforces_claim_trust_and_collects_once(self):
        from shared.job_runtime.tests.test_business import BusinessTests
        from shared.job_runtime import business
        from unittest.mock import patch
        fixture=BusinessTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.profile.update(phase='business',shell=True,writable_roots=[],timeout_seconds=15)
        claim_path=business._gmail_claim_path
        fence=patch.object(business,'_gmail_claim_path',side_effect=lambda workspace,claim,namespace:claim_path(fixture.base,claim,namespace))
        fence.start();self.addCleanup(fence.stop)
        self.claim['slot_id']=fixture.base.name
        self.claim['payload_sha256']=_digest(json.dumps({k:v for k,v in self.claim.items() if k!='payload_sha256'},sort_keys=True,separators=(',',':')))
        fixture.fake(final={'status':'sent','gmail_verified':True,'delivery_verified':True})
        with patch.object(business,'_metadata',wraps=business._metadata) as metadata:
            result=business.run_business(fixture.profile,'synthetic',ROOT,fixture.base/'run',{'gmail_claim':self.claim})
        self.assertEqual(metadata.call_count,1)
        self.assertEqual((result['status'],result['code']),('failed','BUSINESS_GMAIL_EVIDENCE_UNVERIFIED'))
        self.assertEqual(result['receipt']['model_final_evidence_trust'],'untrusted_model_output')
        # Actual synthetic host stream, model final has no nine-field echo.
        fixture.fake(extra='\n'.join('print('+repr(json.dumps(e))+')' for e in self.events[1:]),final={'status':'sent','gmail_verified':True})
        stream=business._stream
        def ordered(*args):
            raw,err,reason=stream(*args)
            lines=bytes(raw).splitlines();starts=[x for x in lines if json.loads(x).get('type')=='thread.started']
            lines=starts+[x for x in lines if x not in starts]
            return _ObservedOutput(b'\n'.join(lines),raw.observations),err,reason
        self.claim['attempt_id']='attempt-success-001'
        self.claim['payload_sha256']=_digest(json.dumps({k:v for k,v in self.claim.items() if k!='payload_sha256'},sort_keys=True,separators=(',',':')))
        with patch.object(business,'_stream',side_effect=ordered):
            result=business.run_business(fixture.profile,'synthetic',ROOT,fixture.base/'second',{'gmail_claim':self.claim})
        self.assertEqual(result['status'],'succeeded')
        self.assertEqual(result['receipt']['final_evidence_trust'],'trusted_operational_host_evidence')
        with patch.object(business,'_metadata') as metadata:
            replay=business.run_business(fixture.profile,'synthetic',ROOT,fixture.base/'replay',{'gmail_claim':self.claim})
        self.assertEqual(replay['code'],'RUNTIME_GMAIL_CLAIM_REPLAY')
        metadata.assert_not_called()
        self.assertFalse((fixture.base/'replay').exists())
        for category in ('format','sensitive_output'):
            self.claim['attempt_id']='attempt-'+category
            self.claim['payload_sha256']=_digest(json.dumps({k:v for k,v in self.claim.items() if k!='payload_sha256'},sort_keys=True,separators=(',',':')))
            with patch.object(business,'_stream',side_effect=ordered), patch.object(business,'_final',side_effect=SummaryError('BUSINESS_FINAL_REJECTED',category=category)):
                failed=business.run_business(fixture.profile,'synthetic',ROOT,fixture.base/('bad-'+category),{'gmail_claim':self.claim})
            self.assertEqual(failed['status'],'failed')
            self.assertEqual(failed['receipt']['gmail_claim'],self.claim)
            self.assertEqual(failed['receipt']['gmail_operational_evidence']['message_id'],self.mid)

    def test_simple_acceptance_email_claim(self):
        from email.message import EmailMessage
        msg=EmailMessage();msg['To']='canary@example.invalid';msg['From']='Sender <canary@example.invalid>';msg['Subject']='acceptance'
        msg.set_content('accepted')
        payload={'to':str(msg['To']),'subject':str(msg['Subject']),'body':msg.get_content()}
        self.rawmime=self.encode(msg.as_bytes())
        self.events=self.events[:2]+[self.event('gmail_send_email','simple-send-001',payload,
            {'id':self.mid,'threadId':self.tid}),self.read(self.mid,'simple-read-001')]
        evidence=_metadata(self.raw())['gmail_observation'][0]
        self.claim_for('text',evidence)
        self.assertEqual(self.receipt()['final_evidence_trust'],'trusted_operational_host_evidence')

    def test_claim_variants_are_pre_send_and_retained(self):
        self.assertEqual(self.receipt()['gmail_claim'],self.claim)
        evidence=_metadata(self.raw())['gmail_observation'][0]
        self.claim_for('raw',evidence)
        self.assertEqual(self.receipt()['final_evidence_trust'],'trusted_operational_host_evidence')
        self.assertEqual(self.receipt()['gmail_claim'],self.claim)
        self.claim['delivery_payload_sha256']='0'*64;self.bind();self.untrusted()

    def test_missing_observations_cannot_be_reconstructed_at_parse_time(self):
        raw=bytes(self.raw())
        self.assertIsNone(_metadata(raw)['gmail_observation'])
        for event in self.events:event['timestamp']='2026-11-05T08:09:10+00:00'
        self.assertIsNone(_metadata(bytes(self.raw()))['gmail_observation'])
        self.assertEqual(self.receipt('2026-11-05T08:09:11+00:00',
                                      '2026-11-05T08:09:12+00:00')['final_evidence_trust'],
                         'untrusted_model_output')

    def test_auxiliary_failure_unknown_duplicate_and_bad_envelope(self):
        import copy
        original=copy.deepcopy(self.events)
        for name in ('gmail_get_profile','sites_get_site','metadata_search'):
            for change in ({'status':'failed'},{'status':'unknown'},{'error':{}},
                           {'id':'x'},{'id':'send-event-001'},
                           {'result':{'structured_content':{'status':'unknown'}}},
                           {'result':{'structured_content':{'isError':True,'message':'CANARY'}}},
                           {'result':{'structured_content':{'value':'x'*1048577}}},
                           {'result':{'structuredContent':{}}}):
                self.events=copy.deepcopy(original)
                aux=self.event(name,'auxiliary-event-001',{},{});aux['item'].update(change)
                self.events.insert(1,aux);self.untrusted()

    def test_no_claim_business_profile_fails_before_child_launch(self):
        from shared.job_runtime.tests.test_business import BusinessTests
        from shared.job_runtime import business
        fixture=BusinessTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.profile.update(phase='business',shell=True,writable_roots=[],timeout_seconds=15)
        for index,final in enumerate(({'status':'sent'}, {'status':'completed','gmail_verified':True},
                                     {'status':'completed','delivery_verified':True},
                                     {'status':'completed','gmail_verified':False})):
            fixture.fake(final=final)
            result=business.run_business(fixture.profile,'synthetic',ROOT,fixture.base/f'case-{index}')
            self.assertEqual((result['status'],result['code']),('failed','BUSINESS_GMAIL_CLAIM_REQUIRED'))

    def test_final_not_required_to_echo_and_workspace_revalidation(self):
        self.final={'status':'sent'}
        self.assertEqual(self.receipt()['final_evidence_trust'],'trusted_operational_host_evidence')
        self.final['report_directory']=str(ROOT/'.job-runtime'/'synthetic')
        self.assertEqual(self.receipt()['final_evidence_trust'],'trusted_operational_host_evidence')
        self.assertEqual(self.receipt(workspace=ROOT/'elsewhere')['final_evidence_trust'],'untrusted_model_output')
        with self.assertRaises(SummaryError):_final('{"status":"sent","status":"failed"}','business',ROOT)


if __name__=='__main__':unittest.main()


class DispatchBoundaryTests(unittest.TestCase):
    def setUp(self):
        from shared.job_runtime.tests.test_business import BusinessTests
        from shared.job_runtime import business
        from unittest.mock import patch
        self.business=business
        self.fixture=BusinessTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.fake(final={'status':'blocked','code':'SYNTHETIC'})
        self.fixture.profile.update(phase='business',shell=True,writable_roots=[])
        claim_path=business._gmail_claim_path
        patcher=patch.object(business,'_gmail_claim_path',side_effect=lambda workspace,claim,namespace:claim_path(self.fixture.base,claim,namespace))
        patcher.start();self.addCleanup(patcher.stop)
        from shared.job_runtime.tests.test_service_gmail_claim import ServiceGmailClaimTests
        owner=ServiceGmailClaimTests();owner.setUp();self.addCleanup(owner.doCleanups)
        self.claim=owner.claim()

    def run_bound(self,**extra):
        return self.business.run_business(self.fixture.profile,'synthetic',ROOT,
            self.fixture.base/'run',{'gmail_claim':self.claim,**extra})

    def test_auth_busy_and_cancel_do_not_consume_then_retry(self):
        import fcntl,threading
        lock=open(self.fixture.home/'runtime.lock','w');self.addCleanup(lock.close)
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.assertEqual(self.run_bound()['code'],'MODEL_AUTH_CACHE_BUSY')
        self.assertIsNone(self.business._check_gmail_claim(ROOT,self.claim,'business'))
        fcntl.flock(lock,fcntl.LOCK_UN)
        cancel=threading.Event();cancel.set()
        self.assertEqual(self.run_bound(cancel_event=cancel)['code'],'BUSINESS_CANCELLED_BEFORE_START')
        self.assertIsNone(self.business._check_gmail_claim(ROOT,self.claim,'business'))
        self.run_bound()
        self.assertEqual(self.business._check_gmail_claim(ROOT,self.claim,'business'),'RUNTIME_GMAIL_CLAIM_REPLAY')

    def test_popen_failure_releases_reservation_and_directory(self):
        from unittest.mock import patch
        with patch.object(self.business.subprocess,'Popen',side_effect=OSError('synthetic')):
            self.assertEqual(self.run_bound()['status'],'retryable')
        self.assertIsNone(self.business._check_gmail_claim(ROOT,self.claim,'business'))
        self.assertFalse((self.fixture.base/'run').exists())
        self.run_bound()
        self.assertEqual(self.run_bound()['code'],'RUNTIME_GMAIL_CLAIM_REPLAY')

    def test_claim_write_failure_before_child_is_retryable(self):
        from unittest.mock import patch
        with patch.object(self.business.os,'fsync',side_effect=OSError('synthetic')),patch.object(self.business.subprocess,'Popen') as child:
            self.assertEqual(self.run_bound()['status'],'retryable');child.assert_not_called()
        self.assertIsNone(self.business._check_gmail_claim(ROOT,self.claim,'business'))
        self.run_bound()

    def test_post_launch_commit_failure_is_unknown_and_restart_fenced(self):
        def fail():raise OSError('synthetic')
        value=self.run_bound(commit_dispatch=fail)
        self.assertEqual(value['status'],'unknown')
        path=self.business._gmail_claim_path(ROOT,self.claim,'business')
        self.assertEqual(json.loads(path.read_text())['phase'],'exposed')
        self.assertEqual(self.run_bound()['code'],'RUNTIME_GMAIL_CLAIM_REPLAY')

    def test_reserved_crash_is_fenced_in_fresh_python_process(self):
        import subprocess,sys,os
        self.assertIsNone(self.business._consume_gmail_claim(ROOT,self.claim,'business'))
        code="import json,sys; from shared.job_runtime.business import _check_gmail_claim; print(_check_gmail_claim(sys.argv[1],json.load(sys.stdin),'business'))"
        result=subprocess.run([sys.executable,'-c',code,str(self.fixture.base)],input=json.dumps(self.claim),text=True,capture_output=True,
                              env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT)},timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'RUNTIME_GMAIL_CLAIM_REPLAY')
